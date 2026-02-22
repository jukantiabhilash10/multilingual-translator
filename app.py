from flask import Flask, render_template, request, jsonify, send_file, make_response, session
import os
import uuid
from deep_translator import GoogleTranslator
from gtts import gTTS
try:
    from PyPDF2 import PdfReader
except ImportError:
    from PyPDF2 import PdfFileReader as PdfReader
import speech_recognition as sr
from pymongo import MongoClient
from datetime import datetime, timedelta
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import traceback
import hashlib
import time
from io import BytesIO
from indic_transliteration.sanscript import transliterate, SCHEMES
import re
from werkzeug.security import generate_password_hash, check_password_hash
from flask import redirect, url_for, flash
from bson.objectid import ObjectId
import logging
from logging.handlers import RotatingFileHandler
import sys

# Import new security and utility packages
try:
    from bleach import clean
except ImportError:
    clean = lambda x, **kw: x

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    HAS_LIMITER = True
except ImportError:
    HAS_LIMITER = False
    Limiter = None

try:
    from flask_wtf.csrf import CSRFProtect
    HAS_CSRF = True
except ImportError:
    HAS_CSRF = False
    CSRFProtect = None

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Optional OAuth support
try:
    from authlib.integrations.flask_client import OAuth
    HAS_OAUTH = True
except ImportError:
    HAS_OAUTH = False
    OAuth = None

from flask_cors import CORS

app = Flask(__name__)

# Use SECRET_KEY from Render environment variables
app.secret_key = os.getenv('SECRET_KEY')

# REQUIRED for Netlify → Render cross-domain cookies
app.config.update(
    SESSION_COOKIE_SAMESITE="None",   # allow cross-site cookies
    SESSION_COOKIE_SECURE=True,       # must be True (Render uses HTTPS)
    SESSION_COOKIE_HTTPONLY=True
)

# Allow only your Netlify frontend
CORS(
    app,
    supports_credentials=True,
    origins=["https://translator-abhi.netlify.app"]
)
# Validate required environment variables on startup
REQUIRED_ENV_VARS = ['MONGO_URI', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET']
MISSING_VARS = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
if MISSING_VARS:
    print(f"[WARN] Missing environment variables: {', '.join(MISSING_VARS)}")
    print("[WARN] App will run with limited functionality")
    print("[INFO] Create a .env file with required variables")

# Setup logging
if not app.debug:
    if not os.path.exists('logs'):
        os.mkdir('logs')
    file_handler = RotatingFileHandler('logs/translator.log', maxBytes=10240000, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info('Translator app startup')

# Setup rate limiting if available
limiter = None
if HAS_LIMITER:
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["200 per day", "50 per hour"]
    )

# Setup CSRF protection if available
csrf = None
if HAS_CSRF:
    csrf = CSRFProtect(app)

# OAuth setup (Google / GitHub) - only if authlib is available
oauth = None
if HAS_OAUTH:
    oauth = OAuth(app)
    
    # Read OAuth client credentials from environment (set these in your env)
    GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
    GITHUB_CLIENT_ID = os.getenv('GITHUB_CLIENT_ID')
    GITHUB_CLIENT_SECRET = os.getenv('GITHUB_CLIENT_SECRET')
    
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
        oauth.register(
            name='google',
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email profile'},
        )
    
    if GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET:
        oauth.register(
            name='github',
            client_id=GITHUB_CLIENT_ID,
            client_secret=GITHUB_CLIENT_SECRET,
            access_token_url='https://github.com/login/oauth/access_token',
            authorize_url='https://github.com/login/oauth/authorize',
            api_base_url='https://api.github.com/',
            client_kwargs={'scope': 'user:email'},
        )

    # Debug/log OAuth registration status
    try:
        print(f"[DEBUG] HAS_OAUTH={HAS_OAUTH}")
        print(f"[DEBUG] GOOGLE_CLIENT_ID={'SET' if GOOGLE_CLIENT_ID else 'MISSING'}, GITHUB_CLIENT_ID={'SET' if GITHUB_CLIENT_ID else 'MISSING'}")
        registered = []
        clients_obj = None
        try:
            clients_obj = getattr(oauth, 'clients', None) or getattr(oauth, '_clients', None) or getattr(oauth, 'registry', None)
        except Exception:
            clients_obj = None
        if clients_obj:
            try:
                # clients_obj may be a dict-like or object with keys
                if hasattr(clients_obj, 'keys'):
                    registered = list(clients_obj.keys())
                else:
                    registered = list(clients_obj)
            except Exception as e:
                print(f"[DEBUG] Failed to list oauth clients: {e}")
        print(f"[DEBUG] OAuth clients registered: {registered}")
    except Exception as e:
        print(f"[DEBUG] OAuth debug logging failed: {e}")

@app.before_request
def ensure_user():
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
        session['session_created'] = datetime.utcnow().isoformat()
    
    # Check if guest session is older than 24 hours and reset if needed
    if session.get('session_created') and not session.get('username'):  # guest session
        if is_session_expired(session.get('session_created')):
            app.logger.info(f"Guest session expired, resetting: {session['user_id']}")
            session.clear()
            session['user_id'] = str(uuid.uuid4())
            session['session_created'] = datetime.utcnow().isoformat()

@app.after_request
def add_header(response):
    """
    Add headers to both force latest content and prevent caching.
    """
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

# MongoDB setup
# Read Mongo URI from environment for safety; fall back to no-DB mode when unavailable
MONGO_URI = os.getenv('MONGO_URI')
client = None
history_collection = None
users_collection = None
# In-memory fallback storage (used when MongoDB is unreachable)
history_in_memory = []
users_in_memory = []

# Token system constants
GUEST_DAILY_LIMIT = 50  # unregistered users get 50 tokens per day
REGISTERED_DAILY_LIMIT = 500  # registered users get 500 tokens per day
TOKENS_PER_WORD = 1  # 1 token per word translated

if MONGO_URI:
    try:
        # Use a short server selection timeout so startup doesn't hang
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        # Force a server selection / connection attempt
        client.admin.command('ping')
        db = client.get_database('translator_db')
        history_collection = db['translation_history']
        users_collection = db['users']
        print('[INFO] Connected to MongoDB')
    except Exception as e:
        print(f"[WARN] MongoDB connection failed: {e}. Falling back to in-memory history.")
        client = None
        history_collection = None
else:
    print('[WARN] MONGO_URI not set; running without MongoDB (in-memory history only).')


# ============ UTILITY FUNCTIONS ============

def sanitize_input(text, max_length=5000):
    """Sanitize user input to prevent XSS and other attacks"""
    if not text or not isinstance(text, str):
        raise ValueError("Invalid input: text must be a non-empty string")
    text = text.strip()
    if len(text) > max_length:
        raise ValueError(f"Input exceeds {max_length} characters")
    # Remove potentially dangerous content
    text = clean(text, strip=True)
    return text


def safe_db_operation(operation_func, fallback_value=None):
    """Wrapper to safely handle DB operations with fallback"""
    try:
        return operation_func()
    except Exception as e:
        app.logger.warning(f"DB operation failed: {e}, using fallback")
        return fallback_value


def is_session_expired(created_timestamp):
    """Check if guest session is older than 24 hours"""
    try:
        created_dt = datetime.fromisoformat(created_timestamp)
        age_hours = (datetime.utcnow() - created_dt).total_seconds() / 3600
        return age_hours > 24
    except:
        return False


# ============ HISTORY HELPER FUNCTIONS ============
def get_history_for_user(user_id):
    try:
        if history_collection:
            return list(history_collection.find({'user_id': user_id}).sort('timestamp', -1))
    except Exception as e:
        print(f"[DEBUG] DB read failed: {e}")
    # Fallback: filter in-memory store and return newest first
    try:
        return sorted([h for h in history_in_memory if h.get('user_id') == user_id], key=lambda x: x.get('timestamp', ''), reverse=True)
    except Exception:
        return []


# User helpers (DB or in-memory)
def get_user_by_username(username):
    try:
        if users_collection:
            return users_collection.find_one({'username': username})
    except Exception as e:
        print(f"[DEBUG] DB user read failed: {e}")
    for u in users_in_memory:
        if u.get('username') == username:
            return u
    return None


def create_user(username, password):
    hashed = generate_password_hash(password)
    today = datetime.utcnow().strftime('%Y-%m-%d')
    try:
        if users_collection:
            res = users_collection.insert_one({
                'username': username, 
                'password': hashed,
                'tokens_used': 0,
                'last_token_reset': today,
                'is_registered': True
            })
            return {
                '_id': str(res.inserted_id), 
                'username': username, 
                'password': hashed,
                'tokens_used': 0,
                'last_token_reset': today,
                'is_registered': True
            }
    except Exception as e:
        print(f"[DEBUG] DB user insert failed: {e}")
    # fallback
    user = {
        '_id': username, 
        'username': username, 
        'password': hashed,
        'tokens_used': 0,
        'last_token_reset': today,
        'is_registered': True
    }
    users_in_memory.append(user)
    return user


# Indic script mapping (used in transliteration)
INDIC_SCRIPT_MAP = {
    'te': 'telugu', 'hi': 'devanagari', 'gu': 'gujarati', 'bn': 'bengali',
    'ta': 'tamil', 'ml': 'malayalam', 'kn': 'kannada', 'pa': 'gurmukhi',
    'mr': 'devanagari', 'ne': 'devanagari', 'si': 'sinhala', 'ur': 'urdu'
}

# Helper to detect script in input text
def detect_indic_script(s):
    """Detect which Indic script the input text uses"""
    if re.search(r"[\u0C00-\u0C7F]", s):
        return 'telugu'
    if re.search(r"[\u0900-\u097F]", s):
        return 'devanagari'
    if re.search(r"[\u0980-\u09FF]", s):
        return 'bengali'
    if re.search(r"[\u0A00-\u0A7F]", s):
        return 'gurmukhi'
    if re.search(r"[\u0A80-\u0AFF]", s):
        return 'gujarati'
    if re.search(r"[\u0B80-\u0BFF]", s):
        return 'tamil'
    if re.search(r"[\u0D00-\u0D7F]", s):
        return 'malayalam'
    if re.search(r"[\u0C80-\u0CFF]", s):
        return 'kannada'
    return None


def verify_user(username, password):
    user = get_user_by_username(username)
    if not user:
        return None
    try:
        if check_password_hash(user.get('password', ''), password):
            return user
    except Exception as e:
        print(f"[DEBUG] Password check failed: {e}")
    return None


# Token management functions
def reset_daily_tokens_if_needed(user):
    """Reset tokens if it's a new day"""
    today = datetime.utcnow().strftime('%Y-%m-%d')
    last_reset = user.get('last_token_reset', '')
    
    if last_reset != today:
        # Reset tokens for new day
        try:
            if users_collection and user.get('_id'):
                users_collection.update_one(
                    {'_id': ObjectId(user.get('_id')) if isinstance(user.get('_id'), str) and len(user.get('_id')) == 24 else user.get('_id')},
                    {'$set': {'tokens_used': 0, 'last_token_reset': today}}
                )
        except Exception as e:
            print(f"[DEBUG] Token reset failed: {e}")
        
        # Update in-memory as well
        for u in users_in_memory:
            if u.get('username') == user.get('username'):
                u['tokens_used'] = 0
                u['last_token_reset'] = today
                break
        
        user['tokens_used'] = 0
        user['last_token_reset'] = today


def get_tokens_limit(user_id):
    """Get daily token limit for user (50 for guest, 500 for registered)"""
    if not user_id:
        return GUEST_DAILY_LIMIT
    
    # Try to find user by user_id (could be from session)
    # For now, check if it's a registered user in the collection
    try:
        if users_collection:
            user = users_collection.find_one({'_id': ObjectId(user_id) if isinstance(user_id, str) and len(user_id) == 24 else user_id})
            if user and user.get('is_registered'):
                return REGISTERED_DAILY_LIMIT
    except Exception as e:
        print(f"[DEBUG] Token limit lookup failed: {e}")
    
    # Check in-memory
    for u in users_in_memory:
        if u.get('_id') == user_id and u.get('is_registered'):
            return REGISTERED_DAILY_LIMIT
    
    return GUEST_DAILY_LIMIT


def get_tokens_used_today(user_id):
    """Get tokens used today by a user"""
    today = datetime.utcnow().strftime('%Y-%m-%d')
    
    try:
        if users_collection:
            user = users_collection.find_one({'_id': ObjectId(user_id) if isinstance(user_id, str) and len(user_id) == 24 else user_id})
            if user and user.get('last_token_reset') == today:
                return user.get('tokens_used', 0)
    except Exception as e:
        print(f"[DEBUG] Tokens used lookup failed: {e}")
    
    # Check in-memory
    for u in users_in_memory:
        if u.get('_id') == user_id and u.get('last_token_reset') == today:
            return u.get('tokens_used', 0)
    
    return 0


def consume_tokens(user_id, word_count):
    """Consume tokens for translation and update user"""
    tokens_needed = word_count * TOKENS_PER_WORD
    today = datetime.utcnow().strftime('%Y-%m-%d')
    
    try:
        if users_collection:
            users_collection.update_one(
                {'_id': ObjectId(user_id) if isinstance(user_id, str) and len(user_id) == 24 else user_id},
                {'$inc': {'tokens_used': tokens_needed}},
                upsert=False
            )
    except Exception as e:
        print(f"[DEBUG] Token consumption failed: {e}")
    
    # Update in-memory
    for u in users_in_memory:
        if u.get('_id') == user_id:
            u['tokens_used'] = u.get('tokens_used', 0) + tokens_needed
            u['last_token_reset'] = today
            break


def check_token_available(user_id, word_count):
    """Check if user has enough tokens. Returns (has_tokens, tokens_used, tokens_limit, tokens_remaining)"""
    tokens_needed = word_count * TOKENS_PER_WORD
    tokens_used = get_tokens_used_today(user_id)
    tokens_limit = get_tokens_limit(user_id)
    tokens_remaining = tokens_limit - tokens_used
    
    has_enough = tokens_remaining >= tokens_needed
    
    return {
        'has_tokens': has_enough,
        'tokens_needed': tokens_needed,
        'tokens_used': tokens_used,
        'tokens_limit': tokens_limit,
        'tokens_remaining': tokens_remaining
    }


# OAuth helper: create or return user from oauth info
def create_or_get_oauth_user(username):
    # username should be unique (email or provider_login)
    user = get_user_by_username(username)
    if user:
        return user
    # create a user with a random password
    random_password = uuid.uuid4().hex
    return create_user(username, random_password)


@app.route('/login/<provider>')
def oauth_login(provider):
    if not HAS_OAUTH or not oauth:
        flash('OAuth is not configured.', 'warning')
        return redirect(url_for('login'))
    try:
        client = oauth.create_client(provider)
    except Exception:
        client = None
    if not client:
        flash(f'OAuth for {provider} is not configured.', 'warning')
        return redirect(url_for('login'))
    redirect_uri = url_for('oauth_callback', provider=provider, _external=True)
    return client.authorize_redirect(redirect_uri)


@app.route('/auth/<provider>/callback')
def oauth_callback(provider):
    if not HAS_OAUTH or not oauth:
        flash('OAuth is not configured.', 'warning')
        return redirect(url_for('login'))
    try:
        client = oauth.create_client(provider)
    except Exception:
        client = None
    if not client:
        flash('OAuth client not available', 'danger')
        return redirect(url_for('login'))

    try:
        token = client.authorize_access_token()
    except Exception as e:
        print(f"[DEBUG] OAuth token error: {e}")
        flash('OAuth authentication failed', 'danger')
        return redirect(url_for('login'))

    # Get user info depending on provider
    user_info = {}
    try:
        if provider == 'google':
            # For Google OIDC, use the full userinfo endpoint URL
            resp = client.get('https://openidconnect.googleapis.com/v1/userinfo', token=token)
            user_info = resp.json()
            # Extract email from userinfo response
            username = user_info.get('email') or user_info.get('sub')
            if not username:
                print(f"[DEBUG] Google userinfo missing email/sub: {user_info}")
                username = None
        elif provider == 'github':
            resp = client.get('user')
            data = resp.json()
            # try email endpoint if no public email
            username = data.get('login')
            if not data.get('email'):
                # fetch primary email
                emails = client.get('user/emails').json()
                primary = next((e for e in emails if e.get('primary') and e.get('verified')), None)
                if primary:
                    username = primary.get('email')
        else:
            username = None
    except Exception as e:
        print(f"[DEBUG] Failed to fetch user info from {provider}: {e}")
        import traceback
        print(f"[DEBUG] Traceback: {traceback.format_exc()}")
        username = None

    if not username:
        flash('Could not determine user identity from provider', 'danger')
        return redirect(url_for('login'))

    # Create or get user
    user = create_or_get_oauth_user(username)
    session['username'] = user['username']
    session['user_id'] = str(user.get('_id', user['username']))
    flash('Logged in successfully', 'success')
    return redirect(url_for('index'))


def save_history_entry(entry):
    try:
        if history_collection:
            return history_collection.insert_one(entry)
    except Exception as e:
        print(f"[DEBUG] DB insert failed: {e}")
    # Fallback: append to in-memory list
    history_in_memory.append(entry)
    class _Res:
        inserted_id = None
    return _Res()

# Font configuration for PDF
class CustomPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.font_cache = {}

    def add_unicode_font(self, font_name, font_path):
        try:
            # Check file extension
            _, ext = os.path.splitext(font_path)
            if ext.lower() not in ['.ttf', '.otf']:
                print(f"[DEBUG] Unsupported font format for {font_name}: {ext}")
                self.font_cache[font_name] = False
                return

            # Try adding font without style parameter first
            try:
                self.add_font(font_name, fname=font_path)
            except Exception:
                # If that fails, try with empty string style
                self.add_font(font_name, '', font_path)
            
            print(f"[DEBUG] Successfully loaded font: {font_name}")
            self.font_cache[font_name] = True
        except Exception as e:
            print(f"[DEBUG] Failed to add font {font_name}: {str(e)}")
            self.font_cache[font_name] = False

    def setup_fonts(self, app_root):
        font_folder = os.path.join(app_root, 'static', 'fonts')
        font_files = {
            'DejaVu': 'DejaVuSans.ttf',
            'NotoSans': 'NotoSans-Regular.ttf',
            'NotoTelugu': 'NotoSansTelugu-Regular.ttf',
            'NotoGujarati': 'NotoSansGujarati-Regular.ttf',
            'NotoDevanagari': 'NotoSansDevanagari-Regular.ttf',
            'NotoBengali': 'NotoSansBengali-Regular.ttf',
            'NotoTamil': 'NotoSansTamil-Regular.ttf',
            'NotoMalayalam': 'NotoSansMalayalam-Regular.ttf',
            'NotoKannada': 'NotoSansKannada-Regular.ttf',
            'NotoPunjabi': 'NotoSansGurmukhi-Regular.ttf',
            'NotoUrdu': 'NotoSansArabic-Regular.ttf',
            'NotoArabic': 'NotoSansArabic-Regular.ttf',
            'NotoChinese': 'NotoSansSC-Regular.otf',
            'NotoJapanese': 'NotoSansJP-Regular.ttf',
            'NotoKorean': 'NotoSansKR-Regular.ttf',
            'NotoHebrew': 'NotoSansHebrew-Regular.ttf',
            'NotoGreek': 'NotoSansGreek-Regular.ttf',
            'NotoRussian': 'NotoSans-Regular.ttf',
            'NotoSansTC': 'NotoSansTC-Regular.ttf',  # Traditional Chinese
            'NotoSansThai': 'NotoSansThai-Regular.ttf', # Thai
        }
        for font_name, font_file in font_files.items():
            font_path = os.path.join(font_folder, font_file)
            if os.path.exists(font_path):
                self.add_unicode_font(font_name, font_path)
            else:
                print(f"[DEBUG] Font missing: {font_path}")
                # Download logic can be added here if needed

    def download_indic_font(self, font_name, font_path):
        # Using Google Fonts CDN for reliable downloads
        font_urls = {
            'NotoTelugu': 'https://fonts.google.com/download?family=Noto+Sans+Telugu',
            'NotoGujarati': 'https://fonts.google.com/download?family=Noto+Sans+Gujarati',
            'NotoDevanagari': 'https://fonts.google.com/download?family=Noto+Sans+Devanagari'
        }
        
        try:
            import requests
            import zipfile
            import io
            
            os.makedirs(os.path.dirname(font_path), exist_ok=True)
            print(f"[DEBUG] Downloading font {font_name} from {font_urls[font_name]}")
            
            response = requests.get(font_urls[font_name])
            response.raise_for_status()
            
            # Extract the regular font file from the zip
            with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
                # Find the regular weight TTF file
                font_file = next(f for f in zip_ref.namelist() if f.endswith('-Regular.ttf'))
                with zip_ref.open(font_file) as font_data:
                    with open(font_path, 'wb') as f:
                        f.write(font_data.read())
            
            self.add_unicode_font(font_name, font_path)
        except Exception as e:
            print(f"[DEBUG] Failed to download {font_name}: {str(e)}")

    def download_cjk_font(self, font_name, font_path):
        # Using Google Fonts CDN for reliable downloads
        font_urls = {
            'NotoChinese': 'https://fonts.google.com/download?family=Noto+Sans+SC',
            'NotoJapanese': 'https://fonts.google.com/download?family=Noto+Sans+JP',
            'NotoKorean': 'https://fonts.google.com/download?family=Noto+Sans+KR'
        }
        
        try:
            import requests
            import zipfile
            import io
            
            os.makedirs(os.path.dirname(font_path), exist_ok=True)
            print(f"[DEBUG] Downloading font {font_name} from {font_urls[font_name]}")
            
            response = requests.get(font_urls[font_name])
            response.raise_for_status()
            
            # Extract the regular font file from the zip
            with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
                # Find the regular weight TTF file
                font_file = next(f for f in zip_ref.namelist() if f.endswith('Regular.otf') or f.endswith('Regular.ttf'))
                with zip_ref.open(font_file) as font_data:
                    with open(font_path, 'wb') as f:
                        f.write(font_data.read())
            
            print(f"[DEBUG] Successfully downloaded font: {font_name}")
            self.add_unicode_font(font_name, font_path)
        except Exception as e:
            print(f"[DEBUG] Failed to download {font_name}: {str(e)}")

    def cell(self, w=0, h=0, txt='', border=0, ln=0, align='', fill=False, link=''):
        from fpdf.enums import XPos, YPos
        # Handle deprecated parameters
        text = txt  # txt renamed to text
        if ln == 0:
            new_x, new_y = XPos.RIGHT, YPos.TOP
        else:
            new_x, new_y = XPos.LMARGIN, YPos.NEXT
        
        try:
            super().cell(w=w, h=h, text=text, border=border, 
                        new_x=new_x, new_y=new_y, 
                        align=align, fill=fill, link=link)
        except UnicodeEncodeError:
            current_font = self.font_family
            if current_font != 'NotoSans' and self.font_cache.get('NotoSans', False):
                self.set_font('NotoSans')
                super().cell(w=w, h=h, text=text, border=border,
                           new_x=new_x, new_y=new_y,
                           align=align, fill=fill, link=link)
                self.set_font(current_font)
            else:
                self.set_font('DejaVu')
                super().cell(w=w, h=h, text=text, border=border,
                           new_x=new_x, new_y=new_y,
                           align=align, fill=fill, link=link)
                self.set_font(current_font)

    def multi_cell(self, w=0, h=0, txt='', border=0, align='', fill=False, split_only=False):
        # Handle deprecated txt parameter
        text = txt
        try:
            super().multi_cell(w=w, h=h, text=text, border=border,
                             align=align, fill=fill, split_only=split_only)
        except UnicodeEncodeError:
            current_font = self.font_family
            if current_font != 'NotoSans' and self.font_cache.get('NotoSans', False):
                self.set_font('NotoSans')
                super().multi_cell(w=w, h=h, text=text, border=border,
                                 align=align, fill=fill, split_only=split_only)
                self.set_font(current_font)
            else:
                self.set_font('DejaVu')
                super().multi_cell(w=w, h=h, text=text, border=border,
                                 align=align, fill=fill, split_only=split_only)
                self.set_font(current_font)

    def set_language_font(self, language_code, size=12):
        font_map = {
            'te': 'NotoTelugu', 'gu': 'NotoGujarati', 'hi': 'NotoDevanagari',
            'mr': 'NotoDevanagari', 'bn': 'NotoBengali', 'ta': 'NotoTamil',
            'ml': 'NotoMalayalam', 'kn': 'NotoKannada', 'pa': 'NotoPunjabi',
            'ur': 'NotoUrdu', 'ar': 'NotoArabic', 
            'zh-CN': 'NotoChinese', 'zh-TW': 'NotoSansTC', 'ja': 'NotoJapanese',
            'ko': 'NotoKorean', 'he': 'NotoHebrew', 'el': 'NotoGreek',
            'ru': 'NotoRussian', 'th': 'NotoSansThai',
        }
        font_name = font_map.get(language_code, 'NotoSans') 
        if self.font_cache.get(font_name, False):
            self.set_font(font_name, size=size)
        else:
            print(f"[DEBUG] Font {font_name} not available, falling back to DejaVu")
            self.set_font('DejaVu', size=size)

# Language configuration (alphabetized, with Auto-Detect)
language_pairs = [
    ("Afrikaans", "af"),
    ("Albanian", "sq"),
    ("Amharic", "am"),
    ("Arabic", "ar"),
    ("Armenian", "hy"),
    ("Azerbaijani", "az"),
    ("Bengali", "bn"),
    ("Bulgarian", "bg"),
    ("Catalan", "ca"),
    ("Chinese (simplified)", "zh-CN"),
    ("Chinese (traditional)", "zh-TW"),
    ("Croatian", "hr"),
    ("Czech", "cs"),
    ("Danish", "da"),
    ("Dutch", "nl"),
    ("English", "en"),
    ("Estonian", "et"),
    ("Filipino", "tl"),
    ("Finnish", "fi"),
    ("French", "fr"),
    ("German", "de"),
    ("Greek", "el"),
    ("Gujarati", "gu"),
    ("Hebrew", "he"),
    ("Hindi", "hi"),
    ("Hungarian", "hu"),
    ("Indonesian", "id"),
    ("Italian", "it"),
    ("Japanese", "ja"),
    ("Kannada", "kn"),
    ("Korean", "ko"),
    ("Malay", "ms"),
    ("Malayalam", "ml"),
    ("Marathi", "mr"),
    ("Nepali", "ne"),
    ("Polish", "pl"),
    ("Portuguese", "pt"),
    ("Punjabi", "pa"),
    ("Romanian", "ro"),
    ("Russian", "ru"),
    ("Serbian", "sr"),
    ("Sinhala", "si"),
    ("Slovak", "sk"),
    ("Spanish", "es"),
    ("Swahili", "sw"),
    ("Swedish", "sv"),
    ("Tamil", "ta"),
    ("Telugu", "te"),
    ("Thai", "th"),
    ("Turkish", "tr"),
    ("Urdu", "ur"),
    ("Vietnamese", "vi"),
    ("Xhosa", "xh"),
    ("Zulu", "zu"),
]
# Sort alphabetically by language name
language_pairs.sort(key=lambda x: x[0])
languages = ["Auto-Detect"] + [name for name, code in language_pairs]
language_codes = ["auto"] + [code for name, code in language_pairs]

# Add this mapping after language_pairs and before routes
language_name_to_code = {name: code for name, code in language_pairs}

gtts_lang_map = {
    "Arabic": "ar",
    "Bengali": "bn",
    "Chinese": "zh-CN",
    "English": "en",
    "French": "fr",
    "German": "de",
    "Gujarati": "gu",
    "Hindi": "hi",
    "Italian": "it",
    "Japanese": "ja",
    "Kannada": "kn",
    "Korean": "ko",
    "Malayalam": "ml",
    "Marathi": "mr",
    "Portuguese": "pt",
    "Punjabi": "pa",
    "Russian": "ru",
    "Spanish": "es",
    "Tamil": "ta",
    "Telugu": "te",
    "Urdu": "ur",
    # Add more as needed
}

@app.route('/')
def index():
    user_history = get_history_for_user(session['user_id'])
    return render_template(
        'index.html',
        languages=languages,
        history=user_history
    )

@app.route('/get_csrf_token', methods=['GET'])
def get_csrf_token():
    """Return CSRF token for AJAX requests"""
    if HAS_CSRF and csrf:
        from flask_wtf.csrf import generate_csrf
        token = generate_csrf()
        return jsonify({'csrf_token': token})
    return jsonify({'csrf_token': ''})

# Apply rate limiting decorator if available
@app.route('/translate', methods=['POST'])
def translate():
    try:
        # Get and sanitize input
        text = request.form.get('text', '').strip()
        lang_from = request.form.get('lang_from', '')
        lang_to = request.form.get('lang_to', '')
        enable_transliteration = request.form.get('transliterate') == 'true'
        
        # Validate inputs
        text = sanitize_input(text, max_length=5000)
        
        if not lang_from or not lang_to:
            return jsonify({'error': 'Language selection required'}), 400
        
        # Check token availability
        word_count = len(text.split())
        token_check = check_token_available(session['user_id'], word_count)
        
        if not token_check['has_tokens']:
            return jsonify({
                'error': 'Insufficient tokens',
                'message': f"You have used {token_check['tokens_used']} of {token_check['tokens_limit']} tokens today. This translation needs {token_check['tokens_needed']} tokens. Please register or wait for the next day.",
                'tokens_used': token_check['tokens_used'],
                'tokens_limit': token_check['tokens_limit'],
                'tokens_remaining': token_check['tokens_remaining']
            }), 429

        # Handle Auto-Detect
        if lang_from == "Auto-Detect":
            lang_from_code = "auto"
        else:
            lang_from_code = language_codes[languages.index(lang_from)]
        lang_to_code = language_codes[languages.index(lang_to)]
        print(f"[DEBUG] lang_from: {lang_from}, lang_from_code: {lang_from_code}")
        print(f"[DEBUG] lang_to: {lang_to}, lang_to_code: {lang_to_code}")
        print(f"[DEBUG] Transliteration enabled: {enable_transliteration}")

        text_to_translate = text
        
        # Handle transliteration if enabled
        if enable_transliteration:
            target_script_lang = None
            # Prioritize explicitly selected source language
            if lang_from_code in INDIC_SCRIPT_MAP:
                target_script_lang = lang_from_code
            # Handle Auto-Detect case by checking the target language
            elif lang_from_code == 'auto' and lang_to_code in INDIC_SCRIPT_MAP:
                target_script_lang = lang_to_code

            try:
                detected = detect_indic_script(text)
                # If input is Latin (no Indic script) and we have a target, transliterate Roman->target_script
                if not detected and target_script_lang:
                    transliterated_text = transliterate(text, 'itrans', INDIC_SCRIPT_MAP[target_script_lang])
                    if transliterated_text and transliterated_text != text:
                        text_to_translate = transliterated_text
                        lang_from_code = target_script_lang
                        print(f"[DEBUG] Roman input transliterated to '{text_to_translate}' and set source lang to '{lang_from_code}'")
                # If input is already in an Indic script but not the expected target, convert script->itrans (romanize)
                elif detected:
                    # If the detected script matches the target script, leave as-is
                    if INDIC_SCRIPT_MAP.get(target_script_lang) == detected:
                        print(f"[DEBUG] Input already in target script '{detected}', no transliteration performed")
                    else:
                        # Transliterate from detected script to itrans (romanize) so translator can detect correctly
                        transliterated_text = transliterate(text, detected, 'itrans')
                        if transliterated_text and transliterated_text != text:
                            text_to_translate = transliterated_text
                            lang_from_code = detected
                            print(f"[DEBUG] Indic input transliterated to itrans: '{text_to_translate}' and set source lang to '{lang_from_code}'")
            except Exception as e:
                print(f"[DEBUG] Transliteration failed: {e}")
                app.logger.warning(f"Transliteration error: {e}")

        # Perform translation
        translated = GoogleTranslator(source=lang_from_code, target=lang_to_code).translate(text_to_translate)
        print(f"[DEBUG] Source text for translation: {text_to_translate}")
        print(f"[DEBUG] Source language for translation: {lang_from_code}")
        print(f"[DEBUG] Target language for translation: {lang_to_code}")
        print(f"[DEBUG] Translated text: {translated}")

        # Consume tokens after successful translation
        consume_tokens(session['user_id'], word_count)

        # Save translation to MongoDB with user_id (or fallback to in-memory)
        result = save_history_entry({
            'user_id': session['user_id'],  # Associate with current user
            'source_text': text, # Always save the original user input
            'translated_text': translated,
            'source_lang': lang_from_code,
            'source_lang_name': lang_from,  # Save name for display
            'target_lang': lang_to_code,    # Save code
            'target_lang_name': lang_to,    # Save name for display
            'timestamp': datetime.utcnow().isoformat()
        })

        # Get remaining tokens and add warning if low
        token_status = check_token_available(session['user_id'], 0)
        response_data = {'translated_text': translated}
        
        # Add warning if tokens are running low
        if token_status['tokens_remaining'] < 10:
            response_data['warning'] = f"⚠️ Only {token_status['tokens_remaining']} tokens remaining today"
        
        return jsonify(response_data)
    
    except ValueError as e:
        app.logger.warning(f"Input validation error: {e}")
        return jsonify({'error': 'Invalid input', 'details': str(e)}), 400
    except Exception as e:
        app.logger.error(f"Translation error: {e}")
        return jsonify({'error': 'Translation failed', 'details': str(e)}), 500

@app.route('/transliterate', methods=['POST'])
def transliterate_text():
    try:
        text = request.form['text']
        lang_to = request.form['lang_to'] # The target language for transliteration
        lang_to_code = language_name_to_code.get(lang_to)
        if not lang_to_code:
            return jsonify({'error': 'Invalid target language for transliteration.'}), 400

        target_script = INDIC_SCRIPT_MAP.get(lang_to_code)
        if not target_script:
            return jsonify({'error': f'Transliteration not supported for {lang_to}.'}), 400

        # Auto-detect direction: if input contains Indic characters, transliterate Indic->Roman (itrans).
        # Otherwise assume Roman input and transliterate itrans->Indic.
        def contains_indic(s):
            return bool(re.search(r"[\u0900-\u0D7F]", s))

        if contains_indic(text):
            src = detect_indic_script(text)
            if not src:
                # fallback to itrans->target if script unknown
                out = transliterate(text, 'itrans', target_script)
            else:
                out = transliterate(text, src, 'itrans')
        else:
            out = transliterate(text, 'itrans', target_script)

        return jsonify({'transliterated_text': out})
    except Exception as e:
        return jsonify({'error': 'Transliteration failed', 'details': str(e)}), 500


@app.route('/register', methods=['GET', 'POST'])
def register():
    try:
        if request.method == 'GET':
            return render_template('register.html')
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash('Username and password required', 'danger')
            return render_template('register.html')
        if get_user_by_username(username):
            flash('Username already taken', 'warning')
            return render_template('register.html')
        user = create_user(username, password)
        # set session to logged-in user
        session['username'] = user['username']
        session['user_id'] = str(user.get('_id', user['username']))
        flash('Registration successful', 'success')
        return redirect(url_for('index'))
    except Exception as e:
        print(f"[DEBUG] Register error: {e}")
        return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    try:
        if request.method == 'GET':
            return render_template('login.html')
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash('Username and password required', 'danger')
            return render_template('login.html')
        user = verify_user(username, password)
        if not user:
            flash('Invalid credentials', 'danger')
            return render_template('login.html')
        session['username'] = user['username']
        session['user_id'] = str(user.get('_id', user['username']))
        flash('Logged in successfully', 'success')
        return redirect(url_for('index'))
    except Exception as e:
        print(f"[DEBUG] Login error: {e}")
        return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('username', None)
    # Reset to anonymous session id
    session['user_id'] = str(uuid.uuid4())
    flash('Logged out', 'info')
    return redirect(url_for('index'))


@app.route('/token_status', methods=['GET'])
def token_status():
    """Get current token status for the user"""
    user_id = session.get('user_id')
    username = session.get('username')
    
    tokens_used = get_tokens_used_today(user_id)
    tokens_limit = get_tokens_limit(user_id)
    tokens_remaining = tokens_limit - tokens_used
    is_registered = bool(username)
    
    return jsonify({
        'is_registered': is_registered,
        'username': username,
        'tokens_used': tokens_used,
        'tokens_limit': tokens_limit,
        'tokens_remaining': tokens_remaining,
        'percent_used': int((tokens_used / tokens_limit * 100) if tokens_limit > 0 else 0)
    })


@app.route('/download_history_pdf', methods=['GET'])
def download_history_pdf():
    try:
        pdf = CustomPDF()
        pdf.setup_fonts(app.root_path)
        pdf.add_page()

        # Set up title
        pdf.set_language_font('en', size=16)
        pdf.cell(w=0, h=10, txt="Translation History", align='C')
        pdf.ln(h=10)

        # Only fetch current user's history (DB or in-memory fallback)
        entries = get_history_for_user(session['user_id'])

        if not entries:
            pdf.set_language_font('en', size=12)
            pdf.cell(w=0, h=10, txt="No translation history found.", align='C')
        else:
            for entry in entries:
                timestamp = datetime.fromisoformat(entry['timestamp']).strftime('%Y-%m-%d %H:%M:%S')

                # Header for each entry
                pdf.set_language_font('en', size=10)
                pdf.cell(w=0, h=6, txt=f"Date: {timestamp}")
                pdf.ln(h=6)
                # Use language name if available, else code
                lang_from_display = entry.get('source_lang_name', entry['source_lang'])
                lang_to_display = entry.get('target_lang_name', entry['target_lang'])
                pdf.cell(w=0, h=6, txt=f"Languages: {lang_from_display} -> {lang_to_display}")
                pdf.ln(h=6)

                # Source text
                pdf.set_language_font(entry['source_lang'], size=11)
                pdf.cell(w=0, h=6, txt="Source Text:")
                pdf.ln(h=6)
                pdf.multi_cell(w=0, h=6, txt=entry['source_text'])
                pdf.ln(h=4)

                # Translated text
                pdf.set_language_font(entry['target_lang'], size=11)
                pdf.cell(w=0, h=6, txt="Translated Text:")
                pdf.ln(h=6)
                pdf.multi_cell(w=0, h=6, txt=entry['translated_text'])
                pdf.ln(h=8)

                # Separator line
                pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
                pdf.ln(h=8)

        try:
            # Generate PDF directly without encoding
            pdf_bytes = bytes(pdf.output())
            if not pdf_bytes:
                raise ValueError("Generated PDF is empty")

            response = make_response(pdf_bytes)
            response.headers['Content-Type'] = 'application/pdf'
            response.headers['Content-Disposition'] = 'attachment; filename=translation_history.pdf'
            return response
        except Exception as e:
            print(f"[DEBUG] Error in PDF generation: {str(e)}")
            print(f"[DEBUG] Traceback: {traceback.format_exc()}")
            return jsonify({'error': 'Failed to generate PDF', 'details': str(e)}), 500

    except Exception as e:
        print(f"[DEBUG] Critical error: {str(e)}")
        print(f"[DEBUG] Traceback: {traceback.format_exc()}")
        return jsonify({'error': 'Failed to generate PDF', 'details': str(e)}), 500

@app.route('/download_translated_pdf', methods=['POST'])
def download_translated_pdf():
    try:
        text = request.form.get('text', '')
        translated_text = request.form.get('translated_text', '')
        source_lang = request.form.get('source_lang', 'en')
        target_lang = request.form.get('target_lang', 'en')

        # Map language names to codes for font selection
        source_lang_code = language_name_to_code.get(source_lang, source_lang)
        target_lang_code = language_name_to_code.get(target_lang, target_lang)

        pdf = CustomPDF()
        pdf.setup_fonts(app.root_path)
        pdf.add_page()

        from datetime import datetime
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        pdf.set_language_font('en', size=10)
        pdf.cell(w=0, h=8, txt=f"Date: {now_str}")
        pdf.ln(h=8)
        pdf.cell(w=0, h=8, txt=f"Languages: {source_lang} -> {target_lang}")
        pdf.ln(h=8)

        pdf.set_language_font('en', size=16)
        pdf.cell(w=0, h=10, txt="Translated Text", align='C')
        pdf.ln(h=10)

        pdf.set_language_font(source_lang_code, size=12)
        pdf.cell(w=0, h=8, txt="Source Text:")
        pdf.ln(h=8)
        pdf.multi_cell(w=0, h=8, txt=text)
        pdf.ln(h=6)

        pdf.set_language_font(target_lang_code, size=12)
        pdf.cell(w=0, h=8, txt="Translated Text:")
        pdf.ln(h=8)
        pdf.multi_cell(w=0, h=8, txt=translated_text)

        pdf_bytes = bytes(pdf.output())
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'attachment; filename=translated_text.pdf'
        return response
    except Exception as e:
        print(f"[DEBUG] Error in /download_translated_pdf: {str(e)}")
        return jsonify({'error': 'Failed to generate PDF', 'details': str(e)}), 500

@app.route('/download_translated_text', methods=['POST'])
def download_translated_text():
    try:
        translated_text = request.form.get('translated_text', '')
        if not translated_text.strip():
            return jsonify({'error': 'No translated text provided'}), 400
        # Create a text file in memory
        from io import BytesIO
        file_stream = BytesIO()
        file_stream.write(translated_text.encode('utf-8'))
        file_stream.seek(0)
        response = send_file(
            file_stream,
            as_attachment=True,
            download_name='translated_text.txt',
            mimetype='text/plain'
        )
        return response
    except Exception as e:
        print(f"[DEBUG] Error in /download_translated_text: {str(e)}")
        return jsonify({'error': 'Failed to generate text file', 'details': str(e)}), 500

@app.route('/history', methods=['GET'])
def history():
    try:
        # Get pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = 10
        
        entries = get_history_for_user(session['user_id'])
        total = len(entries)
        
        # Calculate pagination
        start = (page - 1) * per_page
        end = start + per_page
        paginated_entries = entries[start:end]
        
        history_list = []
        for entry in paginated_entries:
            history_list.append({
                'source_text': entry.get('source_text', ''),
                'translated_text': entry.get('translated_text', ''),
                'source_lang': entry.get('source_lang', ''),
                'source_lang_name': entry.get('source_lang_name', ''),
                'target_lang': entry.get('target_lang', ''),
                'target_lang_name': entry.get('target_lang_name', ''),
                'timestamp': entry.get('timestamp', '')
            })
        
        # Return paginated response
        return jsonify({
            'entries': history_list,
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': (total + per_page - 1) // per_page
        })
    except Exception as e:
        app.logger.error(f"History fetch error: {e}")
        return jsonify({'error': 'Failed to fetch history', 'details': str(e)}), 500

@app.route('/import_pdf', methods=['POST'])
def import_pdf():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        try:
            reader = PdfReader(file)
            content = ""
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    content += text + "\n"
            if not content.strip():
                return jsonify({'error': 'No extractable text found in PDF'}), 400
            return jsonify({'content': content})
        except Exception as e:
            print(f"[DEBUG] PDF import error: {str(e)}")
            return jsonify({'error': 'Failed to read PDF', 'details': str(e)}), 500
    except Exception as e:
        print(f"[DEBUG] Critical PDF import error: {str(e)}")
        return jsonify({'error': 'Failed to import PDF', 'details': str(e)}), 500

@app.route('/import_txt', methods=['POST'])
def import_txt():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        try:
            content = file.read().decode('utf-8', errors='replace')
            if not content.strip():
                return jsonify({'error': 'Text file is empty'}), 400
            return jsonify({'content': content})
        except Exception as e:
            print(f"[DEBUG] TXT import error: {str(e)}")
            return jsonify({'error': 'Failed to read text file', 'details': str(e)}), 500
    except Exception as e:
        print(f"[DEBUG] Critical TXT import error: {str(e)}")
        return jsonify({'error': 'Failed to import text file', 'details': str(e)}), 500

@app.route('/test_backend')
def test_backend():
    return 'Backend is reachable'

@app.route('/speak', methods=['POST'])
def speak():
    try:
        text = request.form.get('text', '')
        lang = request.form.get('lang_to', 'en')
        lang_code = gtts_lang_map.get(lang, 'en')
        if not text.strip():
            return jsonify({'error': 'No text provided'}), 400
        tts = gTTS(text=text, lang=lang_code)
        mp3_fp = BytesIO()
        tts.write_to_fp(mp3_fp)
        mp3_fp.seek(0)
        return send_file(mp3_fp, mimetype='audio/mpeg', as_attachment=False, download_name='speech.mp3')
    except Exception as e:
        print(f"[DEBUG] Error in /speak: {str(e)}")
        return jsonify({'error': 'Speech generation failed', 'details': str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

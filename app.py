from flask import Flask, request, jsonify, session, send_file
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from deep_translator import GoogleTranslator
from utils.pdf_utils import CustomPDF
from utils.tts_utils import text_to_speech
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# SECRET KEY (Set in Render Environment Variables)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

# Required for cross-domain sessions (Netlify → Render)
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="None"
)

# CORS Configuration (Allow only your Netlify frontend)
CORS(
    app,
    supports_credentials=True,
    origins=["https://translator-abhi.netlify.app"]
)

# MongoDB Connection
mongo_uri = os.getenv('MONGO_URI')
db = None
history_collection = None

try:
    if mongo_uri:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        db = client['translation_db']
        history_collection = db['history']
        print("✅ MongoDB connected successfully")
    else:
        print("⚠️ MONGO_URI not set")
except ConnectionFailure as e:
    print(f"⚠️ MongoDB connection failed: {e}")

# In-memory fallback
in_memory_history = {}

@app.before_request
def before_request():
    if 'user_id' not in session:
        session['user_id'] = str(request.remote_addr)

# -----------------------------
# API ROUTES
# -----------------------------

@app.route('/')
def home():
    return jsonify({"message": "Translator API running successfully"})

@app.route('/translate', methods=['POST'])
def translate():
    text = request.form.get('text', '')
    lang_from = request.form.get('lang_from', 'English')
    lang_to = request.form.get('lang_to', 'Telugu')

    try:
        translated_text = GoogleTranslator(
            source='auto',
            target=lang_to.lower()
        ).translate(text)

        user_id = session.get('user_id', 'guest')

        entry = {
            'user_id': user_id,
            'text': text,
            'translated_text': translated_text,
            'source_lang': lang_from,
            'target_lang': lang_to
        }

        if history_collection:
            try:
                history_collection.insert_one(entry)
            except:
                pass

        in_memory_history.setdefault(user_id, []).append(entry)

        return jsonify({'translated_text': translated_text})

    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/history', methods=['GET'])
def get_history():
    user_id = session.get('user_id', 'guest')
    history = []

    if history_collection:
        try:
            history = list(history_collection.find({'user_id': user_id}).limit(50))
        except:
            history = in_memory_history.get(user_id, [])
    else:
        history = in_memory_history.get(user_id, [])

    for entry in history:
        entry.pop('_id', None)

    return jsonify(history)


@app.route('/import_txt', methods=['POST'])
def import_txt():
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file provided'}), 400

    try:
        content = file.read().decode('utf-8')
        return jsonify({'text': content})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/download_translated_pdf', methods=['POST'])
def download_translated_pdf():
    text = request.form.get('text', '')
    translated_text = request.form.get('translated_text', '')

    try:
        pdf = CustomPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.multi_cell(0, 10, f"Original:\n{text}\n\nTranslated:\n{translated_text}")

        file_path = '/tmp/translation.pdf'
        pdf.output(file_path)

        return send_file(
            file_path,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='translation.pdf'
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/download_history_pdf', methods=['GET'])
def download_history_pdf():
    user_id = session.get('user_id', 'guest')
    history = []

    if history_collection:
        try:
            history = list(history_collection.find({'user_id': user_id}))
        except:
            pass

    try:
        pdf = CustomPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=10)
        pdf.multi_cell(0, 8, f"Translation History\n\n")

        for entry in history:
            text = (
                f"{entry.get('source_lang')}:\n"
                f"{entry.get('text')}\n\n"
                f"{entry.get('target_lang')}:\n"
                f"{entry.get('translated_text')}\n\n"
            )
            pdf.multi_cell(0, 6, text)

        file_path = '/tmp/history.pdf'
        pdf.output(file_path)

        return send_file(
            file_path,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='history.pdf'
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/speak', methods=['POST'])
def speak():
    text = request.form.get('text', '')
    lang_code = request.form.get('lang_code', 'en')

    try:
        audio_file = text_to_speech(text, lang_code)
        return send_file(audio_file, mimetype='audio/mpeg')
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/health', methods=['GET'])
def health():
    db_status = "connected" if db else "disconnected"
    return jsonify({'status': 'ok', 'database': db_status})

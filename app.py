from flask import Flask, request, jsonify, session, render_template, send_file
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from deep_translator import GoogleTranslator
from utils.pdf_utils import CustomPDF
from utils.tts_utils import text_to_speech
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

# Enable CORS for cross-origin requests
CORS(app, resources={r"/*": {"origins": "*"}})

# MongoDB connection with error handling
mongo_uri = os.getenv('MONGO_URI')
db = None
history_collection = None

try:
    if mongo_uri:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        # Test connection
        client.admin.command('ping')
        db = client['translation_db']
        history_collection = db['history']
        print("✅ MongoDB connected successfully")
    else:
        print("⚠️ MONGO_URI not set - using in-memory cache")
except ConnectionFailure as e:
    print(f"⚠️ MongoDB connection failed: {e}")
    db = None
    history_collection = None

# In-memory fallback for history
in_memory_history = {}

@app.before_request
def before_request():
    if 'user_id' not in session:
        session['user_id'] = str(request.remote_addr)

@app.route('/')
def index():
    languages = ['English', 'Telugu', 'Spanish', 'French', 'Hindi', 'Kannada', 'Tamil', 'Marathi']
    history = []
    
    if history_collection:
        try:
            history = list(history_collection.find({'user_id': session['user_id']}).limit(10))
        except:
            history = []
    
    return render_template('index.html', languages=languages, history=history)

@app.route('/translate', methods=['POST'])
def translate():
    data = request.form
    text = data.get('text', '')
    lang_from = data.get('lang_from', 'English')
    lang_to = data.get('lang_to', 'Telugu')
    transliterate = data.get('transliterate', 'false') == 'true'

    try:
        translated_text = GoogleTranslator(source='auto', target=lang_to.lower()).translate(text)
        
        # Save to history
        user_id = session.get('user_id', 'guest')
        translation_entry = {
            'user_id': user_id,
            'text': text,
            'translated_text': translated_text,
            'source_lang': lang_from,
            'target_lang': lang_to
        }
        
        if history_collection:
            try:
                history_collection.insert_one(translation_entry)
            except:
                pass
        
        if user_id not in in_memory_history:
            in_memory_history[user_id] = []
        in_memory_history[user_id].append(translation_entry)
        
        return jsonify({'translated_text': translated_text})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/transliterate', methods=['POST'])
def transliterate():
    data = request.form
    text = data.get('text', '')
    lang_to = data.get('lang_to', 'Telugu')
    transliterated_text = text  # Placeholder for actual transliteration
    return jsonify({'transliterated_text': transliterated_text})

@app.route('/history', methods=['GET'])
def get_history():
    user_id = session.get('user_id', 'guest')
    history = []
    
    if history_collection:
        try:
            history = list(history_collection.find({'user_id': user_id}).limit(50))
        except:
            if user_id in in_memory_history:
                history = in_memory_history[user_id]
    else:
        if user_id in in_memory_history:
            history = in_memory_history[user_id]
    
    for entry in history:
        entry.pop('_id', None)
    
    return jsonify(history)

@app.route('/import_txt', methods=['POST'])
def import_txt():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        content = file.read().decode('utf-8')
        return jsonify({'text': content})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/import_pdf', methods=['POST'])
def import_pdf():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        # Simple placeholder - you'd need pdf parser library
        return jsonify({'text': 'PDF import feature coming soon'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/download_translated_pdf', methods=['POST'])
def download_translated_pdf():
    data = request.form
    text = data.get('text', '')
    translated_text = data.get('translated_text', '')
    
    try:
        pdf = CustomPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.multi_cell(0, 10, f"Original: {text}\n\nTranslated: {translated_text}")
        
        pdf_file = '/tmp/translation.pdf'
        pdf.output(pdf_file)
        
        return send_file(pdf_file, mimetype='application/pdf', as_attachment=True, download_name='translation.pdf')
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
        pdf.multi_cell(0, 8, f"Translation History for {user_id}")
        
        for entry in history:
            text = f"{entry.get('source_lang', 'N/A')}: {entry.get('text', '')}\n{entry.get('target_lang', 'N/A')}: {entry.get('translated_text', '')}\n"
            pdf.multi_cell(0, 6, text)
        
        pdf_file = '/tmp/history.pdf'
        pdf.output(pdf_file)
        
        return send_file(pdf_file, mimetype='application/pdf', as_attachment=True, download_name='history.pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/speak', methods=['POST'])
def speak():
    data = request.form
    text = data.get('text', '')
    lang_code = data.get('lang_code', 'en')
    
    try:
        audio_file = text_to_speech(text, lang_code)
        return send_file(audio_file, mimetype='audio/mpeg')
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/health', methods=['GET'])
def health():
    db_status = "connected" if db else "disconnected"
    return jsonify({'status': 'ok', 'database': db_status})

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))

def history():
    history = list(history_collection.find({'user_id': session['user_id']}))
    return jsonify(history)

@app.route('/import_pdf', methods=['POST'])
def import_pdf():
    # Implement PDF import logic here
    pass

@app.route('/import_txt', methods=['POST'])
def import_txt():
    # Implement TXT import logic here
    pass

@app.route('/download_translated_pdf', methods=['POST'])
def download_translated_pdf():
    data = request.form
    pdf = CustomPDF()
    # Implement PDF generation logic here
    return pdf.output()

@app.route('/download_history_pdf', methods=['GET'])
def download_history_pdf():
    # Implement history PDF download logic here
    pass

@app.route('/download_translated_text', methods=['POST'])
def download_translated_text():
    # Implement text download logic here
    pass

@app.route('/speak', methods=['POST'])
def speak():
    data = request.form
    text = data['text']
    lang_code = data['lang_code']
    audio_file = text_to_speech(text, lang_code)
    return send_file(audio_file, mimetype='audio/mpeg')

if __name__ == '__main__':
    app.run(debug=True)
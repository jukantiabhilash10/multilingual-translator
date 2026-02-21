from flask import Flask, request, jsonify, session, render_template
from flask_cors import CORS
from pymongo import MongoClient
from deep_translator import GoogleTranslator
from utils.pdf_utils import CustomPDF
from utils.tts_utils import text_to_speech
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key')

# Enable CORS for cross-origin requests (frontend deployed on Netlify)
CORS(app, resources={r"/api/*": {"origins": "*"}, r"/*": {"origins": "*"}})

client = MongoClient(os.getenv('MONGO_URI'))
db = client['translation_db']
history_collection = db['history']

@app.before_request
def before_request():
    if 'user_id' not in session:
        session['user_id'] = str(request.remote_addr)

@app.route('/')
def index():
    languages = ['English', 'Telugu', 'Spanish', 'French']  # Example languages
    history = list(history_collection.find({'user_id': session['user_id']}))
    return render_template('index.html', languages=languages, history=history)

@app.route('/translate', methods=['POST'])
def translate():
    data = request.form
    text = data['text']
    lang_from = data['lang_from']
    lang_to = data['lang_to']
    transliterate = data.get('transliterate', 'false') == 'true'

    if transliterate:
        # Handle transliteration logic here
        pass

    translated_text = GoogleTranslator(source=lang_from, target=lang_to).translate(text)
    history_collection.insert_one({'user_id': session['user_id'], 'text': text, 'translated_text': translated_text})
    return jsonify({'translated_text': translated_text})

@app.route('/transliterate', methods=['POST'])
def transliterate():
    data = request.form
    text = data['text']
    lang_to = data['lang_to']
    # Implement transliteration logic here
    transliterated_text = text  # Placeholder for actual transliteration
    return jsonify({'transliterated_text': transliterated_text})

@app.route('/history', methods=['GET'])
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
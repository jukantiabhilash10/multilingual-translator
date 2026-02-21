from gtts import gTTS
import os
from flask import send_file

def text_to_speech(text, lang_code, filename='output.mp3'):
    tts = gTTS(text=text, lang=lang_code)
    tts.save(filename)
    return filename

def serve_audio_file(filepath):
    if os.path.exists(filepath):
        return send_file(filepath, mimetype='audio/mpeg')
    else:
        raise FileNotFoundError(f"The file {filepath} does not exist.")
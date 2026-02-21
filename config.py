import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your_default_secret_key'
    MONGO_URI = os.environ.get('MONGO_URI') or 'your_default_mongo_uri'
    DEBUG = os.environ.get('DEBUG', 'False') == 'True'
    LANGUAGES = ['English', 'Telugu', 'Hindi', 'Spanish', 'French']  # Add more languages as needed
    UPLOAD_FOLDER = 'uploads'  # Folder for uploaded files
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # Limit upload size to 16 MB
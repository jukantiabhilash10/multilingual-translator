# Multilingual Translator

## Overview
The Multilingual Translator is a Flask web application that provides translation and transliteration services for multiple languages. It allows users to input text, select source and target languages, and receive translated text. The application also supports file import/export and text-to-speech functionality.

## Features
- **Translation**: Translate text between various languages.
- **Transliteration**: Convert text from one script to another.
- **File Import/Export**: Upload text files for translation and download translated content as PDFs or text files.
- **Voice Input**: Use voice recognition to input text for translation.
- **Translation History**: Keep track of translation history per user session.

## Technologies Used
- **Flask**: A lightweight WSGI web application framework for Python.
- **MongoDB**: A NoSQL database used for storing translation history.
- **gTTS**: Google Text-to-Speech library for converting text to audio.
- **FPDF**: A library for generating PDF documents.

## Installation
1. Clone the repository:
   ```
   git clone <repository-url>
   cd multilingual-translator
   ```

2. Set up a virtual environment:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Set up environment variables:
   Create a `.env` file in the root directory and add your MongoDB URI and secret key:
   ```
   MONGO_URI=<your_mongo_uri>
   SECRET_KEY=<your_secret_key>
   ```

## Running the Application
To run the application locally, use the following command:
```
python app.py
```
The application will be accessible at `http://127.0.0.1:5000/`.

## Testing
Unit tests for the translation functionality can be found in the `tests` directory. To run the tests, use:
```
pytest tests/test_translate.py
```

## Contributing
Contributions are welcome! Please open an issue or submit a pull request for any enhancements or bug fixes.

## License
This project is licensed under the MIT License. See the LICENSE file for more details.
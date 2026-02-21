import unittest
from app import app

class TranslateTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_translate(self):
        response = self.app.post('/translate', data={
            'text': 'hello',
            'lang_from': 'English',
            'lang_to': 'Telugu',
            'transliterate': 'false'
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'translated_text', response.data)

    def test_transliterate(self):
        response = self.app.post('/transliterate', data={
            'text': 'नमस्ते',
            'lang_to': 'English'
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'transliterated_text', response.data)

    def test_history(self):
        response = self.app.get('/history')
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json, list)

if __name__ == '__main__':
    unittest.main()
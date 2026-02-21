from fpdf import FPDF
import os

class CustomPDF(FPDF):
    def setup_fonts(self):
        self.add_font('DejaVu', '', os.path.join('static', 'fonts', 'DejaVuSans.ttf'), uni=True)
        self.add_font('NotoSans', '', os.path.join('static', 'fonts', 'NotoSans.ttf'), uni=True)

    def header(self):
        self.set_font('DejaVu', 'B', 12)
        self.cell(0, 10, 'Translation Document', 0, 1, 'C')

    def footer(self):
        self.set_y(-15)
        self.set_font('DejaVu', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def create_pdf(translated_text, source_lang, target_lang):
    pdf = CustomPDF()
    pdf.add_page()
    pdf.set_font('DejaVu', '', 12)
    
    pdf.multi_cell(0, 10, f'Translated from {source_lang} to {target_lang}:\n\n{translated_text}')
    
    pdf_output_path = os.path.join('output', f'translation_{source_lang}_to_{target_lang}.pdf')
    pdf.output(pdf_output_path)
    
    return pdf_output_path
"""Actual Apple PDFKit/Vision integration, executed on the macOS CI runner."""
import asyncio
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'payload'))
from pdf_reader import read_pdf
from chat_attachments import inlet


@unittest.skipUnless(sys.platform == 'darwin', 'Apple PDFKit and Vision require macOS')
class NativePDFTests(unittest.TestCase):
    def setUp(self):
        from reportlab.pdfgen import canvas
        self.canvas = canvas
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def scanned(self):
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new('RGB', (1100, 280), 'white')
        ImageDraw.Draw(image).text((45, 65), 'SCANNED SAMPLE 6789', font=ImageFont.load_default(size=72), fill='black')
        return image

    def test_real_page_ranges_and_bounded_continuation(self):
        path = self.root / 'pages.pdf'
        document = self.canvas.Canvas(str(path))
        for number in range(1, 5):
            document.drawString(72, 700, 'Verified page number ' + str(number))
            document.showPage()
        document.save()
        result = read_pdf(path.name, self.root, start_page=2, max_pages=1)
        self.assertEqual(result['page_count'], 4)
        self.assertEqual(result['pages'][0]['page'], 2)
        self.assertIn('page number 2', result['pages'][0]['text'])
        self.assertEqual(result['next_page'], 3)
        final = read_pdf(path.name, self.root, start_page=4, max_pages=1)
        self.assertFalse(final['limited'])
        self.assertIsNone(final['next_page'])

    def test_real_mixed_page_keeps_embedded_and_scanned_text(self):
        from reportlab.lib.utils import ImageReader
        path = self.root / 'mixed.pdf'
        document = self.canvas.Canvas(str(path))
        document.drawString(72, 730, 'EMBEDDED DOCUMENT HEADING')
        document.drawImage(ImageReader(self.scanned()), 36, 470, width=540, height=138)
        document.save()
        result = read_pdf(path.name, self.root, ocr=True)
        text = result['pages'][0]['text'].upper()
        self.assertIn('EMBEDDED DOCUMENT HEADING', text)
        self.assertIn('SCANNED', text)
        self.assertIn('6789', text)
        self.assertEqual(result['pages'][0]['method'], 'embedded+ocr')
        self.assertFalse(result['pages'][0]['ocr_error'])

    def test_real_scanned_upload_enters_chat_with_page_evidence_and_handoff_reference(self):
        uploads = self.root / 'webui/data/uploads'
        uploads.mkdir(parents=True)
        source = uploads / 'scanned.pdf'
        self.scanned().save(source, format='PDF', resolution=144)
        record = SimpleNamespace(id='known-upload', user_id='owner', path=str(source), filename='scan.pdf')
        async def lookup(identifier):
            return record
        body = {'messages': [{'role': 'user', 'content': 'Read the scanned document'}],
                'files': [{'type': 'file', 'id': record.id}]}
        result = asyncio.run(inlet(body, {'id': 'owner'}, self.root, uploads, lookup))
        text = result['messages'][0]['content'].upper()
        self.assertIn('SCANNED', text)
        self.assertIn('6789', text)
        self.assertIn('KNOWN-UPLOAD/ATTACHMENT.PDF', text)
        self.assertEqual(result['files'], [])

    def test_corrupt_and_password_locked_documents_are_explicit_errors(self):
        corrupt = self.root / 'corrupt.pdf'
        corrupt.write_bytes(b'%PDF-1.4 corrupt fixture')
        with self.assertRaises(RuntimeError):
            read_pdf(corrupt.name, self.root)
        from reportlab.lib.pdfencrypt import StandardEncryption
        encrypted = self.root / 'encrypted.pdf'
        document = self.canvas.Canvas(str(encrypted), encrypt=StandardEncryption('secret'))
        document.drawString(72, 700, 'Protected text')
        document.save()
        with self.assertRaises(RuntimeError):
            read_pdf(encrypted.name, self.root, ocr=True)


if __name__ == '__main__':
    unittest.main()

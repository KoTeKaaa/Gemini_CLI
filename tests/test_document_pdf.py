import io
import unittest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from gemini_cli.integrations.documents.client import extract_document
from gemini_cli.integrations.documents.worker import extract


def pdf(text=True, encrypted=False):
    writer = PdfWriter()
    for value in ('FIRST_SELECTED', 'SECOND_UNSELECTED'):
        page = writer.add_blank_page(width=300, height=300)
        if text:
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                                     NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
            stream = DecodedStreamObject(); stream.set_data(f'BT /F1 12 Tf 10 200 Td ({value}) Tj ET'.encode())
            page[NameObject('/Contents')] = writer._add_object(stream)
    if encrypted: writer.encrypt('fixture-only')
    stream = io.BytesIO(); writer.write(stream)
    return stream.getvalue()


class DocumentPDFTests(unittest.TestCase):
    def test_selected_page_real_worker_and_partial_extraction(self):
        result = extract_document(pdf(), 'a.pdf', {'pages': '1'})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['fragments'][0]['position']['page'], 1)
        self.assertIn('FIRST_SELECTED', str(result))
        self.assertNotIn('SECOND_UNSELECTED', str(result))
        self.assertTrue(result['partial'])

    def test_scan_encryption_corruption_and_range(self):
        for data, selection, code in [(pdf(False), {'pages': '1'}, 'unsupported'),
                                      (pdf(encrypted=True), {'pages': '1'}, 'unsupported'),
                                      (b'%PDF-invalid', {'pages': '1'}, 'invalid_document'),
                                      (pdf(), {'pages': '0-11'}, 'invalid_selection'),
                                      (pdf(), {}, 'invalid_selection')]:
            with self.subTest(code=code):
                self.assertEqual(extract(data, 'a.pdf', selection)['error']['code'], code)

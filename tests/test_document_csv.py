import unittest
from gemini_cli.integrations.documents.client import extract_document
from gemini_cli.integrations.documents.worker import extract


class DocumentCSVTests(unittest.TestCase):
    def test_unicode_delimiter_headers_and_only_selected_range(self):
        data = 'Имя;Значение;НЕВЫБРАНО\nАня;=2+2;PRIVATE\nБоб;7;PRIVATE'.encode('utf-8-sig')
        result = extract_document(data, 'a.csv', {'cells': 'A1:B2'})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['fragments'][0]['cells'][0]['value'], 'Имя')
        self.assertEqual(result['fragments'][1]['cells'][1]['value'], '=2+2')
        self.assertNotIn('PRIVATE', str(result))
        self.assertNotIn('Боб', str(result))

    def test_encoding_empty_out_of_bounds_and_truncation(self):
        result = extract('Привет;мир'.encode('cp1251'), 'a.csv', {'cells': 'A1:B1', 'encoding': 'cp1251', 'delimiter': ';'})
        self.assertEqual(result['fragments'][0]['cells'][0]['value'], 'Привет')
        result = extract(b'a,b\n1', 'a.csv', {'cells': 'A2:B4'})
        self.assertTrue(result['partial'])
        self.assertIsNone(result['fragments'][0]['cells'][1]['value'])
        for cells in ('XFE1', 'A0', 'C3:A1', 'A1:XFD100'):
            self.assertEqual(extract(b'a', 'a.csv', {'cells': cells})['error']['code'], 'invalid_selection')
        self.assertEqual(extract(b'', 'a.csv', {'cells': 'A1'})['status'], 'error')
        self.assertTrue(extract(b'x' * 30000, 'a.csv', {'cells': 'A1'})['truncated'])

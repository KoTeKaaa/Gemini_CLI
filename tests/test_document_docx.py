import unittest
from gemini_cli.integrations.documents.worker import extract
from gemini_cli.integrations.documents.client import extract_document
from tests.test_document_boundary import package

BODY = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>Первый</w:t></w:r></w:p>
<w:p><w:pPr><w:sectPr/></w:pPr><w:r><w:t>Второй</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Ячейка</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
<w:p><w:r><w:t>Третий</w:t></w:r></w:p><w:sectPr/>
</w:body></w:document>'''


class DocumentDOCXTests(unittest.TestCase):
    def test_paragraph_table_section_positions_and_worker(self):
        data = package(BODY)
        result = extract_document(data, 'a.docx', {'paragraphs': '2'})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['fragments'], [{'position': {'paragraph': 2, 'section': 1}, 'text': 'Второй'}])
        tables = extract(data, 'a.docx', {'tables': '1'})['fragments']
        self.assertEqual(tables[0]['position']['row'], 1)
        self.assertEqual(tables[0]['cells'], ['Ячейка'])
        sections = extract(data, 'a.docx', {'sections': '2'})
        self.assertIn('Третий', str(sections))
        self.assertNotIn('Первый', str(sections))
        self.assertTrue(sections['partial'])

    def test_corrupt_external_entities_and_large_text(self):
        self.assertEqual(extract(b'PK\x03\x04bad', 'a.docx', {'paragraphs': '1'})['status'], 'error')
        value = package(BODY, {'word/_rels/document.xml.rels': '<r TargetMode="External"/>'})
        self.assertEqual(extract(value, 'a.docx', {'paragraphs': '1'})['error']['code'], 'unsupported')
        value = package(BODY.replace('Первый', 'x' * 30000))
        self.assertTrue(extract(value, 'a.docx', {'paragraphs': '1'})['truncated'])
        self.assertEqual(extract(package(BODY), 'a.docx', {'paragraphs': '99'})['error']['code'], 'invalid_selection')

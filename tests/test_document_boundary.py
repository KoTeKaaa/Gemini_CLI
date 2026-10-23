import io
import unittest
import zipfile
from unittest.mock import patch
from gemini_cli.integrations.documents.boundary import inspect, result, DocumentError


def archive(parts, compression=zipfile.ZIP_STORED):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression) as value:
        for name, body in parts.items(): value.writestr(name, body)
    return stream.getvalue()


def package(body='', extra=None, kind='docx'):
    name = 'word/document.xml' if kind == 'docx' else 'xl/workbook.xml'
    return archive({'[Content_Types].xml': '<Types/>', name: body, **(extra or {})})


class DocumentBoundaryTests(unittest.TestCase):
    def test_mime_extension_size_and_absent_dependency(self):
        for data, extension, mime in [(b'%PDF-x', '.exe', ''), (b'text', '.pdf', ''),
                                      (b'%PDF-x', '.pdf', 'text/plain'), (b'', '.csv', '')]:
            with self.assertRaises(DocumentError): inspect(data, extension, mime)
        with patch.dict('sys.modules', {'defusedxml.ElementTree': None}):
            with self.assertRaises(ImportError): inspect(package(), '.docx')
        self.assertTrue(result('a', [{'text': 'x' * 21000}])['truncated'])

    def test_zip_limits_entities_and_external_links(self):
        for extra in ({'../escape': 'x'}, {'word/vbaProject.bin': 'macro'},
                      {'word/_rels/document.xml.rels': '<Relationships><Relationship TargetMode="External" Target="https://example.com"/></Relationships>'}):
            with self.assertRaises(DocumentError): inspect(package(extra=extra), '.docx')
        bomb = archive({'[Content_Types].xml': '<Types/>', 'word/document.xml': 'x' * 500000}, zipfile.ZIP_DEFLATED)
        with self.assertRaises(DocumentError): inspect(bomb, '.docx')
        malicious = package(extra={'a.rels': '<!DOCTYPE x [<!ENTITY x "secret">]><x>&x;</x>'})
        with self.assertRaises(ValueError): inspect(malicious, '.docx')

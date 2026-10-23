import unittest
from unittest.mock import patch
from gemini_cli.integrations.documents.client import extract_document
from gemini_cli.integrations.documents.worker import extract


class DocumentWorkerTests(unittest.TestCase):
    def test_real_worker_invalid_document_and_bounded_request(self):
        result = extract_document(b'not a pdf', 'a.pdf', {'pages': '1'})
        self.assertEqual(result['error']['code'], 'invalid_document')
        self.assertEqual(extract_document(b'x' * (4 * 1024 * 1024 + 1), 'a.csv', {})['error']['code'], 'limit')
        self.assertEqual(extract_document(b'x', 'a.csv', {}, cancelled=lambda: True)['error']['code'], 'cancelled')

    def test_timeout_cancellation_and_absent_parser(self):
        result = extract_document(b'%PDF-x', 'a.pdf', {'pages': '1'}, timeout=0)
        self.assertEqual(result['error']['code'], 'timeout')
        count = []
        def cancelled():
            count.append(1)
            return len(count) > 1
        self.assertEqual(extract_document(b'%PDF-x', 'a.pdf', {}, cancelled=cancelled)['error']['code'], 'cancelled')
        with patch.dict('sys.modules', {'pypdf': None}):
            result = extract(b'%PDF-x', 'a.pdf', {'pages': '1'})
        self.assertEqual(result['error']['code'], 'dependency_missing')

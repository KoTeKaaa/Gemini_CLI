import unittest
import os
from pathlib import Path
import sys
from gemini_cli.client.process import ManagedProcess
from unittest.mock import patch
from gemini_cli.integrations.documents.client import extract_document
from gemini_cli.integrations.documents.worker import extract


class DocumentWorkerTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows Job memory limit')
    def test_windows_job_enforces_memory_limit(self):
        process = ManagedProcess([sys.executable, '-c',
            'import sys;sys.stdin.readline();data=bytearray(256*1024*1024);print("UNEXPECTED_ALLOCATION")'],
            str(Path.cwd()), memory_limit=64 * 1024 * 1024)
        try:
            process.write('go\n')
            self.assertEqual(process.wait(timeout=10), 'completed')
            self.assertNotEqual(process.poll(), 0)
            self.assertNotIn('UNEXPECTED_ALLOCATION', process.stdout.read())
        finally:
            process.close()
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

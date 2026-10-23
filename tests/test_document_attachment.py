import json
from pathlib import Path
import tempfile
import unittest
from gemini_cli.client.draft import Draft
from gemini_cli.client.file_attachment import attach_file
from gemini_cli.tools.local.document import read_document
from gemini_cli.tools.local.workspace import plan_text_file


class DocumentAttachmentTests(unittest.TestCase):
    def test_multiple_selected_documents_no_raw_bytes_and_no_send(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'a.csv').write_bytes(b'name,value,PRIVATE\nuser,7,SECRET')
            Path(root, 'b.csv').write_bytes('Имя;значение'.encode('utf-8'))
            draft = Draft('keep')
            for selection in ('@a.csv#cells=A1:B2', '@b.csv#cells=A1:B1&delimiter=%3B'):
                attach_file(draft, selection, root, snapshots={}, approve=lambda _: True)
            self.assertEqual(len(draft.files), 2)
            self.assertEqual(draft.text, 'keep')
            message = draft.message('task')
            self.assertNotIn('SECRET', message)
            self.assertNotIn('PRIVATE', message)
            self.assertIn('Имя', message)
            self.assertNotIn('bytes', message)
            for _, text in draft.files: self.assertEqual(json.loads(text)['status'], 'ok')

    def test_changed_file_refusal_and_no_default_full_read(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, 'a.csv'); path.write_bytes(b'a,b')
            snapshots = {(root, 'a.csv'): plan_text_file(root, 'a.csv')}
            path.write_bytes(b'changed')
            draft = Draft()
            with self.assertRaises(ValueError):
                attach_file(draft, '@a.csv#cells=A1', root, snapshots=snapshots, approve=lambda _: True)
            self.assertIsNone(attach_file(draft, '@a.csv#cells=A1', root, snapshots={}, approve=lambda _: False))
            with self.assertRaises(ValueError): attach_file(draft, '@a.csv', root, snapshots={}, approve=lambda _: True)
            def approve(_): path.write_bytes(b'after approval'); return True
            self.assertEqual(read_document({'filepath': 'a.csv', 'selection': 'cells=A1'}, root,
                                            approve=approve)['status'], 'error')
            self.assertFalse(draft.files)

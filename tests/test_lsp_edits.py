import tempfile
import unittest
from pathlib import Path
from gemini_cli.tools.local.lsp_tools import documents
from gemini_cli.tools.local.lsp_edits import offset, rename_files, advanced
from gemini_cli.tools.local.changes import ChangeSet


def edit(uri, version=1):
    return {'documentChanges': [{'textDocument': {'uri': uri, 'version': version}, 'edits': [
        {'range': {'start': {'line': 0, 'character': 0}, 'end': {'line': 0, 'character': 3}}, 'newText': 'new'}]}]}


class LSPEditTests(unittest.TestCase):
    def test_project_version_changed_during_diff_approval_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            a, b = Path(root, 'a.py'), Path(root, 'b.py')
            a.write_text('old=1\n'); b.write_text('x=2\n')
            docs = documents(root)
            class Client:
                documents = {a.as_uri(): 1}
                def request(self, *_): return edit(a.as_uri())
            calls = []
            def approve(files):
                calls.append(files)
                if len(calls) == 2:
                    b.write_text('from a import old\n')
                return True
            result = advanced(Client(), 'rename', {}, {'new_name': 'new'}, root, docs,
                              changes=ChangeSet(root), approve=approve)
            self.assertEqual(result['status'], 'error')
            self.assertEqual(a.read_text(), 'old=1\n')

    def test_multifile_rename_uses_write_set_and_detects_conflict(self):
        with tempfile.TemporaryDirectory() as root:
            a, b = Path(root, 'a.py'), Path(root, 'b.py')
            a.write_bytes(b'old=1\r\n'); b.write_text('old=2\n')
            docs = documents(root)
            proposal = edit(a.as_uri())
            proposal['documentChanges'] += edit(b.as_uri())['documentChanges']
            class Client:
                documents = {a.as_uri(): 1, b.as_uri(): 1}
                def request(self, *_): return proposal
            changes = ChangeSet(root)
            args = {'new_name': 'new'}
            def approve(files):
                a.write_text('manual=3\n')
                return True
            result = advanced(Client(), 'rename', {}, args, root, docs, changes=changes, approve=approve)
            self.assertEqual(result['data']['files'][0]['outcome'], 'failed')
            self.assertEqual(b.read_text(), 'old=2\n')
            a.write_bytes(b'old=1\r\n'); docs = documents(root)
            result = advanced(Client(), 'rename', {}, args, root, docs,
                              changes=ChangeSet(root), approve=lambda _: True)
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(a.read_bytes(), b'new=1\r\n')
            self.assertEqual(b.read_text(), 'new=2\n')

    def test_reject_file_operations_versions_overlap_and_utf16(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root, 'a.py'); file.write_text('old=1\n')
            docs = documents(root)
            for value in ({'documentChanges': [{'kind': 'delete', 'uri': file.as_uri()}]},
                          edit(file.as_uri(), 2), {'changeAnnotations': {}}):
                with self.assertRaises(ValueError): rename_files(value, root, docs)
            value = edit(file.as_uri()); value['documentChanges'][0]['edits'] *= 2
            with self.assertRaises(ValueError): rename_files(value, root, docs)
            self.assertEqual(offset('😀x', {'line': 0, 'character': 2}), 1)
            with self.assertRaises(UnicodeError): offset('😀x', {'line': 0, 'character': 1})

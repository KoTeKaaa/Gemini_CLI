"""Опциональный реальный pylsp; активируется только явно указанным исполняемым файлом."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gemini_cli.tools.local.lsp_tools import python_lsp
from gemini_cli.tools.local.changes import ChangeSet
from gemini_cli.tools.local.checkpoints import CheckpointStore
from gemini_cli.tools.local.undo import undo


@unittest.skipUnless(os.environ.get('GEMINI_TEST_PYLSP'), 'Set GEMINI_TEST_PYLSP for real language server')
class LiveLSPTests(unittest.TestCase):
    def test_definition_references_diagnostics_rename_and_undo(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as private:
            a, b = Path(root, 'a.py'), Path(root, 'b.py')
            source = 'def greet():\n    return missing_value\n\ngreet()\n'
            a.write_text(source, encoding='utf-8')
            b.write_text('from a import greet\ngreet()\n', encoding='utf-8')
            changes = ChangeSet(root, store=CheckpointStore(Path(private)))
            with patch.dict(os.environ, {'GEMINI_CLI_PYLSP': os.environ['GEMINI_TEST_PYLSP']}):
                def call(action, line=1, character=5):
                    result = python_lsp({'action': action, 'filepath': 'a.py', 'line': line,
                                         'character': character, 'new_name': 'welcome'}, root,
                                        approve=lambda _: True, changes=changes, confirm_write=lambda _: True)
                    self.assertEqual(result['status'], 'ok', result)
                    return result['data']
                self.assertEqual(call('definition', 4, 1)['locations'][0]['line'], 1)
                self.assertGreaterEqual(len(call('references')['locations']), 3)
                self.assertTrue(any('missing_value' in row['message'] for row in call('diagnostics')['diagnostics']))
                self.assertEqual(len(call('rename')['files']), 2)
            self.assertIn('welcome()', b.read_text())
            undo(changes, approve=lambda: True)
            self.assertEqual(a.read_text(), source)
            self.assertIn('greet()', b.read_text())

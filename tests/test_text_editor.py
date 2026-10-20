import re
from pathlib import Path
import unittest
from unittest.mock import patch
from gemini_cli.client.text_editor import edit_external, editor_command


class ExternalEditorTest(unittest.TestCase):
    def test_separate_editor_returns_exact_saved_text_and_cleans_file(self):
        paths = []
        def edit(command, **kwargs):
            path = Path(command[-1])
            paths.append(path)
            self.assertEqual(path.read_bytes(), b'original\r\n')
            path.write_bytes(b'edited\r\nsecond\n')
        with patch('gemini_cli.client.text_editor.sys.platform', 'linux'), patch('gemini_cli.client.text_editor.editor_command', side_effect=lambda p: ['editor', str(p)]), \
             patch('gemini_cli.client.text_editor.subprocess.run', side_effect=edit):
            self.assertEqual(edit_external('original\r\n'), 'edited\r\nsecond\n')
        self.assertFalse(paths[0].exists())

    def test_failed_editor_preserves_original(self):
        import subprocess
        with patch('gemini_cli.client.text_editor.sys.platform', 'linux'), patch('gemini_cli.client.text_editor.editor_command', return_value=['editor']), \
             patch('gemini_cli.client.text_editor.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'editor')):
            with self.assertRaisesRegex(ValueError, 'Исходное вложение сохранено'):
                edit_external('keep')

    def test_missing_editor_does_not_fall_back_to_inline_prompt(self):
        with patch('gemini_cli.client.text_editor.sys.platform', 'linux'), \
             patch('gemini_cli.client.text_editor.shutil.which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'отдельного окна'):
                editor_command(Path('draft.txt'))

    def test_windows_waits_for_explicit_saved_document(self):
        def save(_):
            path = Path(process.call_args.args[0][-1])
            path.write_bytes(b'windows\r\n')
        with patch('gemini_cli.client.text_editor.sys.platform', 'win32'), \
             patch('gemini_cli.client.text_editor.subprocess.Popen') as process, \
             patch('builtins.input', side_effect=save):
            process.return_value.poll.return_value = 0
            self.assertEqual(edit_external('keep'), 'windows\r\n')
            self.assertEqual(process.call_args.args[0][0], 'notepad.exe')

    def test_unwritable_temporary_directory_is_a_recoverable_error(self):
        with patch('gemini_cli.client.text_editor.tempfile.TemporaryDirectory', side_effect=OSError('full')):
            with self.assertRaisesRegex(ValueError, 'Исходное вложение сохранено'):
                edit_external('keep')

    def test_cleanup_failure_on_editor_error_reports_path_and_retries(self):
        import tempfile
        from types import SimpleNamespace
        from gemini_cli.client.text_editor import cleanup_pending
        with tempfile.TemporaryDirectory() as directory:
            fake = SimpleNamespace(name=directory, cleanup=lambda: None)
            with patch('gemini_cli.client.text_editor.tempfile.TemporaryDirectory', return_value=fake), \
                 patch('gemini_cli.client.text_editor.editor_command', side_effect=ValueError('editor failed')):
                with self.assertRaisesRegex(ValueError, re.escape(directory)):
                    edit_external('keep')
            self.assertTrue((Path(directory) / 'attachment.txt').exists())
            self.assertIsNone(cleanup_pending())
            self.assertFalse(Path(directory).exists())

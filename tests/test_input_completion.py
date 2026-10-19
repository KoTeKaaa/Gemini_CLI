import tempfile
import os
import unittest
from pathlib import Path
from prompt_toolkit.document import Document
from gemini_cli.client.completion import InputCompleter


class CompletionTest(unittest.TestCase):
    def test_commands(self):
        completions = list(InputCompleter(lambda: '.').get_completions(Document('/pa'), None))
        self.assertIn('/paste', [item.text for item in completions])

    def test_files_spaces_unicode_and_secret_filter(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            base = Path(root)
            for name in ['привет мир.py', '.env', 'id_rsa', 'secret.key']:
                (base / name).write_text('unused')
            (base / 'папка').mkdir()
            try:
                (base / 'outside').symlink_to(outside, target_is_directory=True)
            except OSError:
                pass  # Windows без права создания symlink
            completer = InputCompleter(lambda: root)
            results = [item.text for item in completer.get_completions(Document('@'), None)]
            self.assertEqual(set(results), {'@привет мир.py', '@папка' + os.sep})
            self.assertIn((root, 'привет мир.py'), completer.snapshots)
            self.assertEqual(list(completer.get_completions(Document('@../'), None)), [])
            self.assertEqual(list(completer.get_completions(Document('@outside/'), None)), [])
            self.assertEqual(list(completer.get_completions(Document('@привет мир.py:1-3'), None)), [])

import tempfile
import os
import unittest
from pathlib import Path
from prompt_toolkit.document import Document
from gemini_cli.client.completion import InputCompleter


class CompletionTest(unittest.TestCase):
    def test_change_paths_are_scoped_and_removed_after_undo_without_scanning(self):
        from unittest.mock import patch
        from gemini_cli.tools.local.changes import ChangeHistory
        from gemini_cli.tools.local.checkpoints import CheckpointStore
        from gemini_cli.tools.local.undo import undo
        with tempfile.TemporaryDirectory() as base:
            root = Path(base) / "workspace"
            root.mkdir()
            journal = ChangeHistory(str(root), store=CheckpointStore(Path(base) / "private"))
            turn = journal.begin_turn("first")
            item = turn.propose("привет мир.py", "new\n")
            turn.write(item)
            journal.begin_turn("no edits")
            active = [journal]
            completer = InputCompleter(lambda: str(root), change_choices=lambda: list(active[0].active_files()))
            with patch('gemini_cli.client.completion.os.scandir', side_effect=AssertionError("must not scan")):
                for command in ('/diff ', '/undo при'):
                    result = list(completer.get_completions(Document(command), None))
                    self.assertEqual([c.text for c in result], ['привет мир.py'])
                active[0] = ChangeHistory(str(root), store=journal.store)
                self.assertEqual(list(completer.get_completions(Document('/diff '), None)), [])
                active[0] = journal
                undo(journal, selected_paths=[item.before.path], approve=lambda: True)
                self.assertEqual(list(completer.get_completions(Document('/undo '), None)), [])

    def test_mcp_actions_names_and_storage(self):
        names = ['playwright', 'github']
        completer = InputCompleter(lambda: '.', mcp_choices=lambda: names)
        def choices(text):
            return list(completer.get_completions(Document(text), None))
        self.assertEqual([c.text for c in choices('/mcp ')],
                         ['check', 'tools', 'enable', 'disable', 'login', 'logout', 'help'])
        self.assertEqual([c.text for c in choices('/mcp lo')], ['login', 'logout'])
        for action in ('check', 'tools', 'enable', 'disable', 'login', 'logout'):
            items = choices(f'/mcp {action} gi')
            self.assertEqual([c.text for c in items], ['github'])
            self.assertEqual(items[0].start_position, -2)
        self.assertEqual([c.text for c in choices('/mcp login github ')], ['memory', 'keyring'])
        self.assertEqual([c.text for c in choices('/mcp login github k')], ['keyring'])
        names[:] = ['other']
        self.assertEqual([c.text for c in choices('/mcp enable ')], ['other'])
        for text in ('/mcp bogus ', '/mcp login missing ', '/mcp check other extra ', '/mcp \n'):
            self.assertEqual(choices(text), [])

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

    def test_attachment_numbers_and_exact_range_examples(self):
        choices = lambda: [(2, 'изображение screen.png'), (4, 'файл LICENSE:1-20')]
        completer = InputCompleter(lambda: '.', attachment_choices=choices)
        result = list(completer.get_completions(Document('/remove '), None))
        self.assertEqual([item.text for item in result], ['2', '4'])
        self.assertEqual([item.text for item in completer.get_completions(Document('/show #4'), None)], ['4'])
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'LICENSE').write_text('text')
            result = list(InputCompleter(lambda: root).get_completions(Document('@LIC'), None))
            self.assertEqual(result[0].text, '@LICENSE')
            self.assertEqual(result[0].display_meta_text, 'Файл целиком')

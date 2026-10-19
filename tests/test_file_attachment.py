import tempfile
import unittest
from pathlib import Path
from gemini_cli.client.draft import Draft
from gemini_cli.client.file_attachment import attach_file
from gemini_cli.tools.local.workspace import plan_text_file
from tests.test_draft import png


class FileAttachmentTest(unittest.TestCase):
    def test_snapshot_confirm_and_exact_lines(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'файл с пробелом.txt'
            path.write_bytes(b'a\r\nb\nc\r\n')
            snapshot = {(root, path.name): plan_text_file(root, path.name)}
            draft = Draft('keep')
            attach_file(draft, '@' + path.name + ':2-3', root, snapshots=snapshot, approve=lambda _: True)
            path.unlink()
            self.assertEqual(draft.files[0][1], 'b\nc\r\n')
            self.assertIn('b\nc\r\n', draft.message('keep'))
            self.assertEqual(draft.text, 'keep')

    def test_change_denial_secret_binary_range_image(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            (base / 'a').write_text('old')
            snapshot = {(root, 'a'): plan_text_file(root, 'a')}
            (base / 'a').write_text('changed')
            draft = Draft()
            with self.assertRaisesRegex(ValueError, 'изменился'):
                attach_file(draft, '@a', root, snapshots=snapshot, approve=lambda _: True)
            attach_file(draft, '@a', root, snapshots={}, approve=lambda _: False)
            self.assertEqual(draft.files, [])
            for name, content in [('.env', b'key'), ('binary', b'\0a'), ('text', b'line')]:
                (base / name).write_bytes(content)
            for selection in ['@.env', '@binary', '@text:0-1', '@text:1-3', '@../outside']:
                with self.assertRaises(ValueError):
                    attach_file(draft, selection, root, snapshots={}, approve=lambda _: True)
            (base / 'image.png').write_bytes(png())
            attach_file(draft, '@image.png', root, snapshots={}, approve=lambda _: True)
            self.assertEqual(len(draft.images), 1)

    def test_range_is_named_and_bad_syntax_explains_correct_input(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'LICENSE').write_bytes(b'one\ntwo\nthree\n')
            draft = Draft()
            number = attach_file(draft, '@LICENSE:2-3', root, snapshots={}, approve=lambda _: True)
            self.assertEqual(number, 1)
            self.assertEqual(draft.files, [('LICENSE:2-3', 'two\nthree\n')])
            attach_file(draft, '@LICENSE:1', root, snapshots={}, approve=lambda _: True)
            self.assertEqual(draft.files[1], ('LICENSE:1-1', 'one\n'))
            for selection in ('@LICENSE[1-20]', '@LICENSE[:1-20]', '@LICENSE 1-20'):
                with self.assertRaisesRegex(ValueError, '@LICENSE:1-20'):
                    attach_file(draft, selection, root, snapshots={}, approve=lambda _: True)
            before = draft.items()
            result = attach_file(draft, '@LICENSE', root, snapshots={}, approve=lambda _: False)
            self.assertIsNone(result)
            self.assertEqual(draft.items(), before)

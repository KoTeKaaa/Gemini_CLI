import tempfile
import unittest
from pathlib import Path

from gemini_cli.tools.local.edit import prepare_replacement


class FileEditTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.file = self.root / "file.txt"

    def prepare(self, text, old, new):
        self.file.write_bytes(text.encode())
        return prepare_replacement({"filepath": "file.txt", "old_text": old, "new_text": new},
                                   str(self.root), approve=lambda _: True)

    def test_prepare_diff_unicode_newlines_and_deletion_without_writing(self):
        for newline in ("\n", "\r\n"):
            original = f"one{newline}два{newline}three{newline}"
            plan = self.prepare(original, "два", "")
            self.assertEqual(plan.updated, f"one{newline}{newline}three{newline}")
            self.assertIn("-два", plan.diff)
            self.assertEqual(self.file.read_bytes(), original.encode())

    def test_missing_ambiguous_overlapping_empty_and_unchanged_rejected(self):
        for text, old, new in (("aaa", "aa", "b"), ("a a", "a", "b"),
                               ("abc", "missing", "x"), ("abc", "", "x"), ("abc", "abc", "abc")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                self.prepare(text, old, new)
            self.assertEqual(self.file.read_bytes(), text.encode())

    def test_secret_and_escape_rejected(self):
        (self.root / ".env").write_text("PRIVATE")
        for name in (".env", "../outside"):
            with self.subTest(name=name), self.assertRaises((OSError, ValueError)):
                prepare_replacement({"filepath": name, "old_text": "PRIVATE", "new_text": ""},
                                    str(self.root), approve=lambda _: True)

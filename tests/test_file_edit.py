import tempfile
import unittest
import os
import stat
from unittest.mock import patch
from pathlib import Path

from gemini_cli.tools.local.edit import prepare_replacement, replace_in_file


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

    def apply(self, confirm):
        return replace_in_file({"filepath": "file.txt", "old_text": "two", "new_text": "два"},
                               str(self.root), approve=lambda _: True, confirm_diff=confirm)

    def test_apply_preserves_newlines_and_permissions(self):
        for newline in (b"\n", b"\r\n"):
            self.file.write_bytes(newline.join([b"one", b"two", b"three"]))
            if os.name == "posix":
                self.file.chmod(0o640)
            result = self.apply(lambda diff: "-two" in diff)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(self.file.read_bytes(), newline.join([b"one", "два".encode(), b"three"]))
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o640)

    def test_denial_interrupt_change_and_write_failure(self):
        def interrupt(_diff):
            raise KeyboardInterrupt()
        def changed(_diff):
            self.file.write_text("changed")
            return True
        for confirm in (lambda _: False, interrupt, changed):
            self.file.write_text("one\ntwo\nthree")
            result = self.apply(confirm)
            self.assertEqual(result["status"], "error")
            self.assertNotIn("два", self.file.read_text())
        self.file.write_text("one\ntwo\nthree")
        with patch("gemini_cli.tools.local.files.os.replace", side_effect=OSError):
            self.assertEqual(self.apply(lambda _: True)["status"], "error")
        self.assertEqual(self.file.read_text(), "one\ntwo\nthree")
        self.assertEqual(list(self.root.glob(".gemini-write-*")), [])

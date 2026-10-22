import os
from pathlib import Path
import tempfile
import unittest

from gemini_cli.tools.local.changes import ChangeSet, snapshot


class ChangesTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "file.txt"
        self.path.write_bytes(b"manual\r\nold\r\n")
        self.changes = ChangeSet(str(self.root), "turn")

    def test_actual_diff_uses_user_version_without_git(self):
        item = self.changes.propose("file.txt", "manual\r\nnew\r\n")
        self.assertEqual(item.before.data, b"manual\r\nold\r\n")
        self.assertEqual(item.diff(), "")
        self.assertIn("+new", item.diff(proposed=True))
        self.path.write_bytes(item.proposed)
        self.changes.applied(item)
        self.assertEqual(item.actual.data, item.proposed)
        self.assertIn("-old", item.diff())
        self.assertIn("применено", self.changes.summary())

    def test_denial_and_partial_success_are_separate(self):
        denied = self.changes.propose("file.txt", "denied")
        denied.status = "denied"
        written = self.changes.propose("new.txt", "new")
        (self.root / "new.txt").write_bytes(written.proposed)
        self.changes.applied(written)
        self.assertEqual(denied.diff(), "")
        self.assertEqual(self.path.read_bytes(), denied.before.data)
        self.assertIn("отклонено", self.changes.summary())
        self.assertIn("применено", self.changes.summary())

    def test_change_after_preview_and_actual_mismatch_rejected(self):
        item = self.changes.propose("file.txt", "agent")
        self.path.write_text("manual later")
        with self.assertRaises(ValueError):
            self.changes.validate(item)
        with self.assertRaises(ValueError):
            self.changes.applied(item)
        self.assertIsNone(item.actual)

    def test_secret_escape_binary_and_symlink_rejected(self):
        (self.root / ".env").write_text("secret")
        (self.root / "binary").write_bytes(b"\x00")
        for name in (".env", "../escape", "binary", ".git/config"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                snapshot(str(self.root), name)
        if os.name == "posix":
            (self.root / "alias").symlink_to(self.path)
            with self.assertRaises(ValueError):
                snapshot(str(self.root), "alias")

    def test_no_final_newline_diff_is_unambiguous(self):
        self.path.write_bytes(b"old")
        item = self.changes.propose("file.txt", "new")
        diff = item.diff(proposed=True)
        self.assertIn("-old\n\\ No newline", diff)
        self.assertIn("+new\n\\ No newline", diff)

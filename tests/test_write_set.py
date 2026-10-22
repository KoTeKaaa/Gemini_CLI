import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gemini_cli.tools.local.changes import ChangeSet
from gemini_cli.tools.local.checkpoints import CheckpointStore
from gemini_cli.tools.local.write_set import write_set


class WriteSetTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.root = base / "workspace"
        self.root.mkdir()
        self.path = self.root / "file.txt"
        self.path.write_bytes(b"manual\r\n")
        self.changes = ChangeSet(str(self.root), store=CheckpointStore(base / "private"))

    def write(self, **kwargs):
        return write_set([{"filepath": "file.txt", "content": "after\r\n"}], self.changes,
                         approve=lambda _: True, **kwargs)

    def test_checkpoint_before_write_and_exact_newlines(self):
        self.assertEqual(self.write()[0]["status"], "Успешно записан")
        item = self.changes.entries[0]
        self.assertEqual(self.changes.store.load(item), b"manual\r\n")
        self.assertEqual(self.path.read_bytes(), b"after\r\n")

    def test_changed_after_diff_and_symlink_substitution(self):
        def change(_):
            self.path.write_text("later")
            return True
        self.assertIn("Ошибка", self.write(confirm_diff=change)[0]["status"])
        self.assertEqual(self.path.read_text(), "later")
        if os.name == "posix":
            def link(_):
                self.path.unlink()
                self.path.symlink_to(self.root / "other")
                return True
            self.assertIn("Ошибка", self.write(confirm_diff=link)[0]["status"])
            self.assertFalse((self.root / "other").exists())

    def test_checkpoint_disk_failure_prevents_write(self):
        with patch.object(self.changes.store, "save", side_effect=OSError("disk full")):
            self.assertIn("Ошибка", self.write()[0]["status"])
        self.assertEqual(self.path.read_bytes(), b"manual\r\n")

    def test_refusal_and_cancel_do_not_write(self):
        self.write(confirm_diff=lambda _: False)
        self.assertEqual(self.changes.entries[0].status, "denied")
        self.write(cancelled=lambda: True)
        self.assertEqual(self.changes.entries[-1].status, "skipped")
        self.assertEqual(self.path.read_bytes(), b"manual\r\n")

    def test_selected_fragments_are_written_and_original_proposal_retained(self):
        from gemini_cli.tools.local.hunks import hunks, selected_version
        before = "".join(f"line{i}\r\n" for i in range(30)).encode()
        self.path.write_bytes(before)
        proposed = before.replace(b"line1\r\n", b"first\r\n").replace(b"line25\r\n", b"last\r\n")
        def select(changes, items):
            item = items[0]
            item.selected = selected_version(item.before.data, hunks(item.before.data, item.proposed)[:1])
        write_set([{"filepath": "file.txt", "content": proposed.decode()}], self.changes,
                  approve=lambda _: True, select=select)
        item = self.changes.entries[0]
        self.assertEqual(item.proposed, proposed)
        self.assertEqual(item.actual.data, before.replace(b"line1\r\n", b"first\r\n"))
        self.assertEqual(self.changes.store.load(item), before)

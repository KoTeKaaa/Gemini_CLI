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

    def test_second_file_changed_after_selection_blocks_all_writes(self):
        other = self.root / "other.txt"
        other.write_text("old other")
        def changed(_):
            other.write_text("manual other")
            return True
        result = write_set([{"filepath": "file.txt", "content": "agent"},
                            {"filepath": "other.txt", "content": "agent other"}], self.changes,
                           approve=changed)
        self.assertTrue(all("Ошибка" in r["status"] for r in result))
        self.assertEqual(self.path.read_bytes(), b"manual\r\n")
        self.assertEqual(other.read_text(), "manual other")

    def test_disk_error_and_cancellation_report_partial_result(self):
        from gemini_cli.tools.local.files import atomic_write_text
        files = [{"filepath": "file.txt", "content": "first"}, {"filepath": "second", "content": "second"}]
        calls = []
        def write(path, text, **kwargs):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("disk full")
            return atomic_write_text(path, text, **kwargs)
        with patch("gemini_cli.tools.local.files.atomic_write_text", side_effect=write):
            result = write_set(files, self.changes, approve=lambda _: True)
        self.assertEqual(result[0]["status"], "Успешно записан")
        self.assertIn("disk full", result[1]["status"])
        self.assertEqual(self.changes.entries[0].status, "applied")
        self.assertIsNone(self.changes.entries[1].actual)
        self.assertFalse((self.root / "second").exists())
        # Repeat with cancellation triggered by completion of the first file.
        self.path.write_text("before")
        result = write_set([{"filepath": "file.txt", "content": "changed"}, files[1]], self.changes,
                           approve=lambda _: True, cancelled=lambda: self.path.read_bytes() == b"changed")
        self.assertEqual(result[0]["status"], "Успешно записан")
        self.assertIn("Пропущено", result[1]["status"])

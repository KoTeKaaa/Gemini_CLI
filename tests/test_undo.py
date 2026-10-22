import os
from pathlib import Path
import stat
import tempfile
import unittest

from gemini_cli.tools.local.changes import ChangeSet
from gemini_cli.tools.local.checkpoints import CheckpointStore
from gemini_cli.tools.local.undo import undo


class UndoTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "workspace"
        self.root.mkdir()
        self.path = self.root / "file"
        self.path.write_bytes(b"manual\r\n")
        self.path.chmod(0o640)
        self.changes = ChangeSet(str(self.root), store=CheckpointStore(self.base / "private"))

    def write(self, path="file", text="agent\r\n"):
        item = self.changes.propose(path, text)
        self.changes.write(item)
        return item

    def undo(self):
        return undo(self.changes, approve=lambda: True)

    def test_restore_repeated_writes_new_file_permissions_and_repeat(self):
        mode = stat.S_IMODE(self.path.stat().st_mode)
        self.write()
        self.write(text="second\r\n")
        self.write("new", "new")
        results = self.undo()
        self.assertTrue(all(r["status"] == "Восстановлено" for r in results))
        self.assertEqual(self.path.read_bytes(), b"manual\r\n")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), mode)
        self.assertFalse((self.root / "new").exists())
        self.assertIn("Нет применённых", self.undo()[0]["status"])

    def test_later_edit_missing_file_and_manual_chmod_block_restore(self):
        self.write()
        self.path.write_text("later")
        self.assertIn("Конфликт", self.undo()[0]["status"])
        self.assertEqual(self.path.read_text(), "later")
        self.path.unlink()
        self.assertIn("Конфликт", self.undo()[0]["status"])
        self.assertFalse(self.path.exists())

    def test_missing_corrupt_checkpoint_and_partial_undo(self):
        item = self.write()
        self.write("new", "new")
        (self.changes.store.directory / (item.checkpoint + ".json")).write_bytes(b"{}")
        results = self.undo()
        self.assertIn("Конфликт", results[0]["status"])
        self.assertEqual(results[1]["status"], "Восстановлено")
        self.assertEqual(self.path.read_bytes(), b"agent\r\n")
        (self.changes.store.directory / (item.checkpoint + ".json")).unlink()
        self.assertIn("Конфликт", self.undo()[0]["status"])

    def test_manual_edit_between_agent_writes_is_preserved(self):
        self.write()
        self.path.write_text("manual during turn")
        self.write(text="second")
        self.assertIn("Конфликт", self.undo()[0]["status"])
        self.assertEqual(self.path.read_text(), "second")

    @unittest.skipUnless(os.name == "posix", "POSIX permissions")
    def test_mode_conflict_and_symlink_do_not_touch_target(self):
        self.write()
        self.path.chmod(0o600)
        self.assertIn("Конфликт", self.undo()[0]["status"])
        self.path.unlink()
        other = self.root / "other"
        other.write_text("manual")
        self.path.symlink_to(other)
        self.assertIn("Конфликт", self.undo()[0]["status"])
        self.assertEqual(other.read_text(), "manual")

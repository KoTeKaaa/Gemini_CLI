import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from gemini_cli.tools.local.changes import ChangeSet
from gemini_cli.tools.local.checkpoints import CheckpointStore


class CheckpointTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "workspace"
        self.root.mkdir()
        self.store = CheckpointStore(self.base / "private")
        self.changes = ChangeSet(str(self.root), store=self.store)

    def save(self, name="new.txt"):
        item = self.changes.propose(name, "after")
        item.checkpoint = self.store.save(item, str(self.root))
        return item

    def test_new_and_existing_with_permissions_and_crlf(self):
        self.assertIsNone(self.store.load(self.save()))
        path = self.root / "old.txt"
        path.write_bytes(b"before\r\n")
        path.chmod(0o640)
        item = self.save("old.txt")
        self.assertEqual(self.store.load(item), b"before\r\n")
        self.assertEqual(item.before.mode, stat.S_IMODE(path.stat().st_mode))
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.store.directory.stat().st_mode), 0o700)
            for file in self.store.directory.iterdir():
                self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)

    def test_corrupt_and_missing_checkpoint_rejected(self):
        item = self.save()
        file = self.store.directory / (item.checkpoint + ".json")
        file.write_bytes(b"{}")
        with self.assertRaises(ValueError):
            self.store.load(item)
        file.unlink()
        with self.assertRaises(OSError):
            self.store.load(item)

    def test_size_expiration_and_write_failure(self):
        item = self.save()
        file = self.store.directory / (item.checkpoint + ".json")
        os.utime(file, (0, 0))
        self.store.cleanup()
        self.assertFalse(file.exists())
        self.store.max_bytes = 1
        with self.assertRaises(OSError):
            self.save()
        self.store.max_bytes = 10000
        with patch("gemini_cli.tools.local.checkpoints.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.save()
        self.assertEqual(list(self.store.directory.iterdir()), [])

    def test_workspace_and_secret_never_checkpointed(self):
        self.store.directory = self.root / "private"
        with self.assertRaises(ValueError):
            self.save()
        with self.assertRaises(ValueError):
            self.changes.propose(".env", "secret")

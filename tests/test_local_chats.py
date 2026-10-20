from pathlib import Path
import sqlite3
import stat
import os
import tempfile
import unittest

from gemini_cli.client.local_chats import LocalChats


class LocalChatsTest(unittest.TestCase):
    def test_restart_isolation_delete_and_redaction(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalChats(Path(root))
            chat = store.create("first")
            store.append(chat["id"], [{"role": "user", "content": "task"},
                         {"role": "tool", "name": "read_local_files", "content": "private"}])
            resumed = LocalChats(Path(root))
            self.assertEqual(resumed.list()[0]["title"], "first")
            self.assertNotIn("private", str(resumed.read(chat["id"])))
            self.assertEqual(LocalChats(Path(root), "other").list(), [])
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(store.path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(store.path.parent.stat().st_mode), 0o700)
            self.assertTrue(resumed.delete(chat["id"]))
            self.assertFalse(resumed.delete(chat["id"]))
            with self.assertRaises(LookupError):
                resumed.read(chat["id"])

    def test_failed_batch_is_atomic_and_temporary_store_has_no_files(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalChats(Path(root), temporary=True)
            self.addCleanup(store.close)
            chat = store.create("RAM")
            with self.assertRaises(sqlite3.IntegrityError):
                store.append(chat["id"], [{"role": "user", "content": "first"},
                                         {"role": "forged", "content": "bad"}])
            self.assertEqual(store.read(chat["id"]), [])
            self.assertEqual(list(Path(root).iterdir()), [])

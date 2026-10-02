import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class FileSandboxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"HOME": home}):
            cls.client = importlib.import_module("main")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.base = root / "workspace"
        self.base.mkdir()
        self.sibling = root / "workspace-other"
        self.sibling.mkdir()
        (self.base / "inside.txt").write_text("inside", encoding="utf-8")
        (self.sibling / "outside.txt").write_text("outside", encoding="utf-8")
        (self.base / "outside-link").symlink_to(self.sibling, target_is_directory=True)
        (self.base / "inside-link").symlink_to(self.base / "inside.txt")

    def test_read_resolves_paths_and_blocks_escape(self):
        paths = [
            "inside.txt", "inside-link", "./inside.txt",
            "../workspace-other/outside.txt", "outside-link/outside.txt",
            str(self.sibling / "outside.txt"),
        ]
        with patch.object(self.client.console, "print"):
            result = json.loads(self.client.handle_read_files({"filepaths": paths}, str(self.base)))
        for path in paths[:3]:
            self.assertEqual(result[path], "inside")
        for path in paths[3:]:
            self.assertIn("Доступ заблокирован", result[path])

    def test_write_resolves_paths_and_blocks_escape(self):
        files = [
            {"filepath": "new.txt", "content": "new"},
            {"filepath": "inside-link", "content": "changed"},
            {"filepath": "../workspace-other/outside.txt", "content": "bad"},
            {"filepath": "outside-link/new.txt", "content": "bad"},
            {"filepath": str(self.sibling / "outside.txt"), "content": "bad"},
        ]
        with patch.object(self.client.console, "print"), patch("builtins.input", return_value="y"):
            result = json.loads(self.client.handle_write_files({"files": files}, str(self.base)))
        self.assertEqual([item["status"] for item in result[:2]], ["Успешно записан"] * 2)
        self.assertEqual([item["status"] for item in result[2:]], ["Заблокировано песочницей"] * 3)
        self.assertEqual((self.base / "new.txt").read_text(encoding="utf-8"), "new")
        self.assertEqual((self.base / "inside.txt").read_text(encoding="utf-8"), "changed")
        self.assertEqual((self.sibling / "outside.txt").read_text(encoding="utf-8"), "outside")
        self.assertFalse((self.sibling / "new.txt").exists())


if __name__ == "__main__":
    unittest.main()

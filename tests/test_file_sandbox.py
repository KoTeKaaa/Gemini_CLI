import importlib
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
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

    def test_failed_write_preserves_original_and_reports_each_file(self):
        original_temp_file = tempfile.NamedTemporaryFile
        calls = 0

        @contextmanager
        def fail_first_write(**kwargs):
            nonlocal calls
            calls += 1
            with original_temp_file(**kwargs) as file_obj:
                if calls == 1:
                    class FailingWriter:
                        name = file_obj.name

                        def write(self, content):
                            file_obj.write(content[:2])
                            raise OSError("write failed")

                    yield FailingWriter()
                else:
                    yield file_obj

        files = [
            {"filepath": "inside.txt", "content": "replacement"},
            {"filepath": "new.txt", "content": "new"},
        ]
        with (patch.object(self.client.console, "print") as printed,
              patch("builtins.input", return_value="y"),
              patch.object(self.client.tempfile, "NamedTemporaryFile", side_effect=fail_first_write)):
            result = json.loads(self.client.handle_write_files({"files": files}, str(self.base)))

        self.assertIn("write failed", result[0]["status"])
        self.assertEqual(result[1]["status"], "Успешно записан")
        self.assertEqual((self.base / "inside.txt").read_text(encoding="utf-8"), "inside")
        self.assertEqual((self.base / "new.txt").read_text(encoding="utf-8"), "new")
        self.assertEqual(list(self.base.glob(".gemini-write-*")), [])
        output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
        self.assertIn("inside.txt: Ошибка: write failed", output)
        self.assertIn("new.txt: Успешно записан", output)
        self.assertNotIn("Изменения успешно применены", output)


if __name__ == "__main__":
    unittest.main()

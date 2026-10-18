import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gemini_cli.tools.local.search import find_files


class LocalSearchTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "workspace"
        self.root.mkdir()

    def write(self, name, text="example"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_names_unicode_and_exclusions(self):
        self.write("src/пример.py")
        self.write(".git/private.py")
        self.write(".env")
        self.write("key.pem")
        (self.root / "escape").symlink_to(self.root.parent, target_is_directory=True)
        result = find_files({"pattern": "*.py"}, str(self.root))
        self.assertEqual(result["data"]["paths"], ["src/пример.py"])
        self.assertEqual(find_files({"pattern": "*.java"}, str(self.root))["data"]["paths"], [])
        self.assertEqual(find_files({"pattern": "../*"}, str(self.root))["status"], "error")

    def test_entry_result_and_access_limits_are_reported(self):
        for index in range(5):
            self.write(f"{index}.py")
        self.assertTrue(find_files({}, str(self.root), max_entries=2)["truncated"])
        self.assertEqual(len(find_files({}, str(self.root), max_results=2)["data"]["paths"]), 2)
        with patch("gemini_cli.tools.local.search.os.scandir", side_effect=PermissionError):
            result = find_files({}, str(self.root))
        self.assertTrue(result["truncated"])
        self.assertEqual(result["data"]["skipped"], 1)

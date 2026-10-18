import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gemini_cli.tools.local.search import find_files, search_text


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

    def test_text_search_requires_approval_and_reports_lines(self):
        self.write("пример.txt", "one\nneedle строка\nneedle again\n")
        self.write(".env", "needle PRIVATE")
        self.write("binary.txt", "needle\x00binary")
        with patch("gemini_cli.tools.local.search.read_text_snapshot") as read:
            result = search_text({"query": "needle"}, str(self.root), approve=lambda _: False)
        read.assert_not_called()
        self.assertEqual(result["error"]["code"], "denied")
        result = search_text({"query": "needle"}, str(self.root), approve=lambda _: True)
        self.assertEqual([match["line"] for match in result["data"]["matches"]], [2, 3])
        self.assertTrue(search_text({"query": "needle"}, str(self.root),
                                   approve=lambda _: True, max_results=1)["truncated"])
        self.assertEqual(search_text({"query": ""}, str(self.root), approve=lambda _: True)["status"], "error")

    def test_text_search_rejects_changed_file_after_approval(self):
        file = self.write("file.txt", "before")
        def approve(_scope):
            file.unlink()
            file.symlink_to(self.write(".env", "needle PRIVATE"))
            return True
        result = search_text({"query": "needle"}, str(self.root), approve=approve)
        self.assertEqual(result["data"]["matches"], [])
        self.assertEqual(result["data"]["skipped"], 1)

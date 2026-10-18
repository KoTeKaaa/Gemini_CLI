import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from gemini_cli.tools.local.files import read_file_lines


class ReadFileLinesTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.file = self.root / "file.txt"
        self.args = {"filepath": "file.txt", "start_line": 2, "end_line": 3}

    def test_numbering_lf_crlf_unicode_eof_and_empty(self):
        for newline in ("\n", "\r\n"):
            self.file.write_bytes(newline.join(["one", "два", "three", "four"]).encode())
            result = read_file_lines(self.args, str(self.root), approve=lambda _: True)
            self.assertEqual(result["data"]["lines"], [{"line": 2, "text": "два"}, {"line": 3, "text": "three"}])
        self.file.write_bytes(b"")
        self.assertEqual(read_file_lines(self.args, str(self.root), approve=lambda _: True)["data"]["lines"], [])

    def test_invalid_denied_secret_and_changed_files(self):
        self.file.write_text("one\ntwo\nthree")
        approve = Mock(return_value=False)
        result = read_file_lines({**self.args, "start_line": 0}, str(self.root), approve=approve)
        self.assertEqual(result["status"], "error")
        approve.assert_not_called()
        self.assertEqual(read_file_lines(self.args, str(self.root), approve=approve)["error"]["code"], "denied")
        def replace(_scope):
            self.file.unlink()
            (self.root / ".env").write_text("PRIVATE")
            self.file.symlink_to(self.root / ".env")
            return True
        self.assertEqual(read_file_lines(self.args, str(self.root), approve=replace)["status"], "error")

    def test_line_and_character_limits(self):
        self.file.write_text("one\ntwo\nthree\nfour")
        result = read_file_lines(self.args, str(self.root), approve=lambda _: True, max_lines=1)
        self.assertTrue(result["truncated"])
        result = read_file_lines(self.args, str(self.root), approve=lambda _: True, max_chars=2)
        self.assertEqual(result["data"]["lines"], [{"line": 2, "text": "tw"}])
        self.assertTrue(result["truncated"])

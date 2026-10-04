import importlib
import io
import logging
import os
import tempfile
import unittest
from unittest.mock import patch


class ToolLoggingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"HOME": home}):
            cls.app = importlib.import_module("main")

    def test_log_contains_only_known_tool_name(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        self.app.logger.addHandler(handler)
        try:
            calls = [
                {"name": "write_local_files", "args": {"files": [
                    {"path": "private.txt", "content": "SECRET-TOKEN"}
                ]}},
                {"name": "unknown\nSECRET-NAME", "args": {"value": "SECRET-ARGS"}},
            ]
            history = []
            with patch.object(self.app, "handle_write_files", return_value="saved"):
                self.app.execute_tool_calls(calls, history, "/work")
        finally:
            self.app.logger.removeHandler(handler)

        self.assertEqual(output.getvalue().splitlines(), [
            "Tool вызов: write_local_files",
            "Tool вызов: unknown",
        ])
        self.assertEqual(history[0]["args"]["files"][0]["content"], "SECRET-TOKEN")


if __name__ == "__main__":
    unittest.main()

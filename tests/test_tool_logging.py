import importlib
import io
import logging
import os
import tempfile
import unittest
from unittest.mock import Mock, patch


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

    def test_mixed_batch_preserves_order_and_call_metadata(self):
        names = ["read_local_files", "write_local_files", "execute_command"]
        calls = [{"name": name, "args": {"index": index}, "call_id": f"call-{index}",
                  "thought_signature": f"signature-{index}"}
                 for index, name in enumerate(names)]
        history = []
        handler = Mock(side_effect=["read", "written", "executed"])
        with (patch.object(self.app, "handle_read_files", handler),
              patch.object(self.app, "handle_write_files", handler),
              patch.object(self.app, "handle_execute_command", handler)):
            self.app.execute_tool_calls(calls, history, "/work")
        self.assertEqual([call.args for call in handler.call_args_list],
                         [({"index": index}, "/work") for index in range(3)])
        self.assertEqual([item["role"] for item in history], ["model"] * 3 + ["tool"] * 3)
        self.assertEqual([item["content"] for item in history[3:]], ["read", "written", "executed"])
        self.assertEqual([item["call_id"] for item in history],
                         [f"call-{index}" for index in range(3)] * 2)
        self.assertEqual([item["thought_signature"] for item in history[:3]],
                         [f"signature-{index}" for index in range(3)])


if __name__ == "__main__":
    unittest.main()

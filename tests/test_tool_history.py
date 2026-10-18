import json
import unittest

from gemini_cli.server.tool_history import persistent_tool_message


class ToolHistoryTest(unittest.TestCase):
    def test_private_arguments_and_results_are_removed_idempotently(self):
        for name in ("search_text", "read_file_lines", "replace_in_file"):
            for role in ("model", "tool"):
                with self.subTest(name=name, role=role):
                    content, args = persistent_tool_message(role, name, "PRIVATE",
                        {"query": "PRIVATE", "old_text": "PRIVATE", "new_text": "PRIVATE",
                         "filepath": "file.py", "start_line": 1})
                    self.assertNotIn("PRIVATE", content + json.dumps(args))
                    self.assertEqual(args["filepath"], "file.py")
                    self.assertEqual(persistent_tool_message(role, name, content, args), (content, args))

    def test_web_history_keeps_only_sources_and_bounded_text(self):
        content = json.dumps({"status": "ok", "data": {
            "url": "https://example.com", "text": "x" * 2000, "html": "PRIVATE"}})
        filtered, _ = persistent_tool_message("tool", "read_url", content, None)
        self.assertNotIn("PRIVATE", filtered)
        result = json.loads(filtered)
        self.assertEqual(len(result["data"]["text"]), 1000)
        self.assertEqual(result["data"]["url"], "https://example.com")

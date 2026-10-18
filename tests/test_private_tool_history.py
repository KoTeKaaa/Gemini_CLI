import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gemini_cli.tools.local.search import search_text
from gemini_cli.tools.local.files import read_file_lines
from gemini_cli.tools.local.edit import replace_in_file
from tests import test_tool_continuation as fixtures


class PrivateToolHistoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {"API_KEY": "test-key", "SUPABASE_URL": "https://example.supabase.co",
                                    "SUPABASE_ANON_KEY": "test-anon-key"}):
            cls.server = importlib.import_module("server")

    def test_actual_local_results_are_filtered_on_save_and_restore(self):
        db = fixtures.FakeDb()
        self.server.save_message_to_db(db, "chat-1", "user", "Task")
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "file.txt").write_text("PRIVATE-OLD\nline two")
            operations = [
                ("search_text", {"query": "PRIVATE-OLD"}, search_text),
                ("read_file_lines", {"filepath": "file.txt", "start_line": 1, "end_line": 2}, read_file_lines),
                ("replace_in_file", {"filepath": "file.txt", "old_text": "PRIVATE-OLD", "new_text": "PRIVATE-NEW"}, replace_in_file),
            ]
            for name, args, handler in operations:
                options = {"approve": lambda _: True}
                if name == "replace_in_file":
                    options["confirm_diff"] = lambda _: True
                live = handler(args, root, **options)
                self.assertEqual(live["status"], "ok")
                if name != "replace_in_file":
                    self.assertIn("PRIVATE-OLD", json.dumps(live))
                self.server.save_message_to_db(db, "chat-1", "model", "tool call", name, args)
                self.server.save_message_to_db(db, "chat-1", "tool", json.dumps(live), name)
        # Legacy unfiltered rows must also be scrubbed when reopening a chat.
        db.messages.append({"chat_id": "chat-1", "role": "tool", "name": "search_text", "content": "PRIVATE-LEGACY"})
        stored = json.dumps(db.messages[:-1])
        replay = str(self.server.build_history_from_db(db, "chat-1"))
        self.assertIn("search_text", replay)
        for marker in ("PRIVATE-OLD", "PRIVATE-NEW", "PRIVATE-LEGACY"):
            self.assertNotIn(marker, stored + replay)
        self.assertEqual(self.server.build_history_from_db(db, "another-chat"), [])

    def test_web_history_is_bounded_and_replayable(self):
        db = fixtures.FakeDb()
        self.server.save_message_to_db(db, "chat-1", "user", "Task")
        self.server.save_message_to_db(db, "chat-1", "model", "call", "read_url", {"url": "https://example.com"})
        self.server.save_message_to_db(db, "chat-1", "tool", json.dumps({"status": "ok", "data": {
            "url": "https://example.com", "text": "x" * 1001 + "PRIVATE-TAIL", "html": "PRIVATE-HTML"}}), "read_url")
        replay = str(self.server.build_history_from_db(db, "chat-1"))
        self.assertIn("https://example.com", replay)
        self.assertNotIn("PRIVATE", replay)

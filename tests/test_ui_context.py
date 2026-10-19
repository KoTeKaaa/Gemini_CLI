import importlib
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from gemini_cli.client.completion import COMMANDS
from gemini_cli.runtime.compaction import completed_boundaries


class UIContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"HOME": home}):
            cls.app = importlib.import_module("main")

    def test_chat_search_explicit_no_extra_api_calls(self):
        client = Mock()
        client.get_chats.return_value = [
            {"id": "a", "title": "Same", "created_at": "2026-01-01"},
            {"id": "b", "title": "Other", "created_at": "2026-01-01"}]
        with patch.object(self.app, "radiolist_dialog") as dialog, patch("builtins.input", return_value="same") as prompt:
            dialog.return_value.run.side_effect = ["search", "a"]
            self.assertEqual(self.app.show_chat_menu(client, current_id="a"), ("a", False))
            values = dialog.call_args.kwargs["values"]
            self.assertIn("текущий", values[-1][1])
            self.assertNotIn("b", [key for key, _ in values])
            prompt.assert_called_once()
            client.get_chats.assert_called_once()
        with patch.object(self.app, "radiolist_dialog") as dialog, patch("builtins.input") as prompt:
            dialog.return_value.run.return_value = "temporary"
            self.assertEqual(self.app.show_chat_menu(client), (None, True))
            prompt.assert_not_called()

    def test_explicit_history_limit_and_summary_payload(self):
        rows = [{"role": "user", "content": "question"}]
        summary = {"summary": "context", "boundary_id": "event"}
        payload = self.app.build_stream_payload(rows, None, "model", True, summary=summary)
        self.assertEqual(payload["summary_boundary"], "event")
        with self.assertRaises(ValueError):
            self.app.build_stream_payload(rows * 1001, None, "model", True)
        for command in ("/clear", "/compact", "/fork"):
            self.assertIn(command, COMMANDS)

    def test_compact_cancellation_drops_late_candidate(self):
        backend = Mock()
        with patch.object(self.app, "WorkView"), patch.object(self.app, "run_cancellable", side_effect=InterruptedError):
            result = self.app.compact_context(backend, [], None, "model")
        self.assertEqual(result["reason"], "cancelled")
        self.assertIsNone(result["summary"])

    def test_fork_boundaries_only_explicit_completed_turns(self):
        rows = [{"role": "user", "content": "q", "id": "u", "turn_id": "turn", "status": "completed"},
                {"role": "model", "content": "a", "id": "m", "turn_id": "turn", "status": "completed"}]
        self.assertEqual(completed_boundaries(rows), [rows[1]])
        rows[1]["status"] = "running"
        self.assertEqual(completed_boundaries(rows), [])
        rows[1]["status"] = "legacy"
        self.assertEqual(completed_boundaries(rows), [])

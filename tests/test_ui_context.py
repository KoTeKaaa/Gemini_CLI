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

    def test_main_clear_only_temporary_preserves_model_and_cwd(self):
        from gemini_cli.client.draft import Draft
        for selected, expected in [((None, True), ""), (("saved", False), "draft")]:
            draft = Draft("draft")
            draft.add_text_file("file", "contents")
            backend = Mock(mode="local")
            backend.get_history.return_value = []
            with patch.object(self.app, "show_chat_menu", return_value=selected), \
                 patch.object(self.app, "Draft", side_effect=[draft, Draft()]), \
                 patch.object(self.app, "PromptSession") as session, \
                 patch.object(self.app, "print_banner"), patch.object(self.app.console, "print"):
                session.return_value.prompt.side_effect = ["/clear", "exit"]
                self.app.main(backend)
                second = session.return_value.prompt.call_args_list[1]
                self.assertEqual(second.kwargs["default"], expected)
                self.assertIn("gemini-3.5-flash-lite", str(second.args[0]))
                backend.stream_chat.assert_not_called()
                backend.delete_chat.assert_not_called()

    def test_chat_switch_restores_unsent_draft(self):
        from gemini_cli.client.draft import Draft
        draft = Draft("unfinished")
        draft.add_text_file("file", "contents")
        backend = Mock(mode="local")
        backend.get_history.return_value = []
        with patch.object(self.app, "show_chat_menu", side_effect=[(None, True), ("saved", False), (None, True)]), \
             patch.object(self.app, "Draft", side_effect=[draft, Draft()]), \
             patch.object(self.app, "PromptSession") as session, \
             patch.object(self.app, "print_banner"), patch.object(self.app.console, "print"):
            session.return_value.prompt.side_effect = ["/chat", "/chat", "exit"]
            self.app.main(backend)
            self.assertEqual([call.kwargs["default"] for call in session.return_value.prompt.call_args_list],
                             ["unfinished", "", "unfinished"])
            backend.stream_chat.assert_not_called()

    def test_temporary_turn_has_stable_completed_ids(self):
        from uuid import UUID
        backend = Mock(mode="local")
        with patch.object(self.app, "show_chat_menu", return_value=(None, True)), \
             patch.object(self.app, "PromptSession") as session, \
             patch.object(self.app, "print_banner"), patch.object(self.app.console, "print"), \
             patch.object(self.app.console, "rule"), patch.object(self.app, "open_stream") as stream, \
             patch.object(self.app, "WorkView"), \
             patch.object(self.app, "display_stream_response", return_value=("answer", [])):
            stream.return_value.status_code = 200
            session.return_value.prompt.side_effect = ["first", "second", "exit"]
            self.app.main(backend)
            rows = stream.call_args.args[1]["history"]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["turn_id"], rows[1]["turn_id"])
            self.assertEqual([row["status"] for row in rows], ["completed", "completed"])
            self.assertNotEqual(rows[0]["id"], rows[1]["id"])
            for row in rows:
                UUID(row["id"])

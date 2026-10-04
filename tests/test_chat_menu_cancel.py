import importlib
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


class ChatMenuCancelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"HOME": home}):
            cls.app = importlib.import_module("main")

    def test_escape_at_start_returns_without_opening_prompt(self):
        client = Mock()
        client.get_chats.return_value = []
        with patch.object(self.app, "get_server_url", return_value="http://127.0.0.1:8000"), \
                patch.object(self.app, "GeminiAPIClient", return_value=client), \
                patch.object(self.app, "radiolist_dialog") as dialog, \
                patch.object(self.app, "PromptSession") as session:
            dialog.return_value.run.return_value = None
            self.app.main()
        session.assert_not_called()
        client.stream_chat.assert_not_called()

    def test_escape_after_chat_command_keeps_temporary_chat_history(self):
        client = Mock()
        client.get_chats.return_value = []
        client.stream_chat.return_value = SimpleNamespace(status_code=200)
        with patch.object(self.app, "get_server_url", return_value="http://127.0.0.1:8000"), \
                patch.object(self.app, "GeminiAPIClient", return_value=client), \
                patch.object(self.app, "radiolist_dialog") as dialog, \
                patch.object(self.app, "PromptSession") as session, \
                patch.object(self.app, "print_banner"), \
                patch.object(self.app, "display_stream_response", side_effect=[
                    ("first answer", []), ("second answer", [])
                ]), patch.object(self.app.console, "print"), \
                patch.object(self.app.console, "rule"):
            dialog.return_value.run.side_effect = ["temporary", None]
            session.return_value.prompt.side_effect = ["first", "/chat", "second", "exit"]
            self.app.main()

        self.assertEqual(dialog.return_value.run.call_count, 2)
        self.assertEqual(client.stream_chat.call_count, 2)
        second_payload = client.stream_chat.call_args_list[1].args[0]
        self.assertIsNone(second_payload["chat_id"])
        self.assertEqual(second_payload["history"], [
            {"role": "user", "content": "first"},
            {"role": "model", "content": "first answer"},
        ])

    def test_escape_after_chat_command_keeps_persistent_chat(self):
        client = Mock()
        client.get_chats.return_value = [
            {"id": "chat-1", "title": "Saved", "created_at": "2026-10-04T00:00:00"}
        ]
        client.stream_chat.return_value = SimpleNamespace(status_code=200)
        with patch.object(self.app, "get_server_url", return_value="http://127.0.0.1:8000"), \
                patch.object(self.app, "GeminiAPIClient", return_value=client), \
                patch.object(self.app, "radiolist_dialog") as dialog, \
                patch.object(self.app, "PromptSession") as session, \
                patch.object(self.app, "print_banner"), \
                patch.object(self.app, "display_stream_response", return_value=("answer", [])), \
                patch.object(self.app.console, "print"), \
                patch.object(self.app.console, "rule"):
            dialog.return_value.run.side_effect = ["chat-1", None]
            session.return_value.prompt.side_effect = ["/chat", "message", "exit"]
            self.app.main()

        self.assertEqual(client.stream_chat.call_args.args[0]["chat_id"], "chat-1")


if __name__ == "__main__":
    unittest.main()

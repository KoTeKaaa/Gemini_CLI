import importlib
import io
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException


class ChatErrorsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            "API_KEY": "test-key",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "test-anon-key",
        }):
            cls.server = importlib.import_module("server")
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"HOME": home}):
            cls.main = importlib.import_module("main")

    def test_failed_message_insert_reaches_stream_client(self):
        db = Mock()
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "chat-1"}
        ]
        db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = []
        db.table.return_value.insert.return_value.execute.side_effect = OSError("database unavailable")
        user = self.server.UserContext("user-1", db)
        model = SimpleNamespace(models=SimpleNamespace(
            generate_content_stream=lambda **_kwargs: self.fail("Model was called")))
        with patch.object(self.server, "client", model), patch.object(
            self.server, "StreamingResponse",
            side_effect=lambda generator, **_kwargs: SimpleNamespace(body_iterator=generator),
        ), patch("builtins.print"):
            response = self.server.stream_chat(
                self.server.StreamChatPayload(chat_id="chat-1", message="Hello"), user
            )
            events = [json.loads(part.decode().removeprefix("data: "))
                      for part in response.body_iterator]
        self.assertEqual(events, [{
            "type": "error", "content": "[Ошибка сервера: Не удалось сохранить сообщение в БД]"
        }])

    def test_failed_response_insert_reports_error_after_text(self):
        db = Mock()
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "chat-1"}
        ]
        db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = []
        db.table.return_value.insert.return_value.execute.side_effect = [
            SimpleNamespace(data=[{}]), OSError("database unavailable")
        ]
        user = self.server.UserContext("user-1", db)
        model = SimpleNamespace(models=SimpleNamespace(generate_content_stream=lambda **_kwargs: [
            SimpleNamespace(function_calls=None, text="Answer")
        ]))
        with patch.object(self.server, "client", model), patch.object(
            self.server, "StreamingResponse",
            side_effect=lambda generator, **_kwargs: SimpleNamespace(body_iterator=generator),
        ), patch("builtins.print"):
            response = self.server.stream_chat(
                self.server.StreamChatPayload(chat_id="chat-1", message="Hello"), user
            )
            events = [json.loads(part.decode().removeprefix("data: "))
                      for part in response.body_iterator]
        self.assertEqual([event["type"] for event in events], ["text", "error"])
        self.assertIn("Не удалось сохранить сообщение", events[-1]["content"])

    def test_failed_history_read_stops_before_save_and_model_call(self):
        for history in (None, [{"role": "user", "content": "Client history"}]):
            with self.subTest(history=history):
                db = Mock()
                db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                    {"id": "chat-1"}
                ]
                db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.side_effect = OSError(
                    "history unavailable"
                )
                model = SimpleNamespace(models=SimpleNamespace(
                    generate_content_stream=lambda **_kwargs: self.fail("Model was called")))
                with patch.object(self.server, "client", model), patch("builtins.print"), \
                        self.assertRaises(HTTPException) as caught:
                    self.server.stream_chat(
                        self.server.StreamChatPayload(chat_id="chat-1", message="Hello", history=history),
                        self.server.UserContext("user-1", db),
                    )
                self.assertEqual(caught.exception.status_code, 503)
                db.table.return_value.insert.assert_not_called()

    def test_chat_list_returns_500_when_database_is_unavailable(self):
        db = Mock()
        db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.side_effect = OSError(
            "database unavailable"
        )
        with patch("builtins.print"), self.assertRaises(HTTPException) as caught:
            self.server.get_chats(self.server.UserContext("user-1", db))
        self.assertEqual(caught.exception.status_code, 500)

    def test_chat_list_distinguishes_empty_and_http_errors(self):
        client = self.main.GeminiAPIClient("https://example.com")
        for status, data, expected in ((200, [], []), (401, None, None), (500, None, None)):
            with self.subTest(status=status):
                response = Mock(status_code=status)
                response.json.return_value = data
                with patch.object(client, "_authorized_request", return_value=response), \
                        patch.object(self.main.console, "print") as printed:
                    self.assertEqual(client.get_chats(), expected)
                if status == 200:
                    printed.assert_not_called()
                else:
                    self.assertIn(str(status) if status == 500 else "Сессия истекла",
                                  str(printed.call_args))

    def test_chat_menu_stays_closed_when_list_fails(self):
        client = Mock()
        client.get_chats.return_value = None
        with patch.object(self.main, "radiolist_dialog") as dialog:
            self.assertIsNone(self.main.show_chat_menu(client))
        dialog.assert_not_called()

    def test_stream_error_does_not_accept_partial_answer(self):
        response = Mock()
        response.iter_lines.return_value = iter([
            b'data: {"type": "text", "content": "Partial"}',
            b'data: {"type": "error", "content": "Save failed"}',
        ])
        output = io.StringIO()
        with patch.object(self.main.console, "status") as status, \
                patch.object(self.main.console, "print"), \
                patch.object(self.main.sys, "stdout", output):
            status.return_value.start.return_value = None
            status.return_value.stop.return_value = None
            self.assertEqual(self.main.display_stream_response(response, False), ("", []))


if __name__ == "__main__":
    unittest.main()

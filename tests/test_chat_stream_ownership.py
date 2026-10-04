import importlib
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException


class FakeQuery:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = {}
        self.row = None

    def select(self, *_args):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def insert(self, row):
        self.row = row
        return self

    def execute(self):
        self.db.queries.append((self.table, self.filters.copy(), self.row))
        if self.row is not None:
            self.db.messages.append(self.row)
            return SimpleNamespace(data=[self.row])
        rows = self.db.chats if self.table == "chats" else self.db.messages
        return SimpleNamespace(data=[
            row for row in rows
            if all(row.get(key) == value for key, value in self.filters.items())
        ])


class FakeDb:
    def __init__(self):
        self.chats = [
            {"id": "own", "user_id": "user-a"},
            {"id": "foreign", "user_id": "user-b"},
        ]
        self.messages = []
        self.queries = []

    def table(self, name):
        return FakeQuery(self, name)


class StreamChatOwnershipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            "API_KEY": "test-key",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "test-anon-key",
        }):
            cls.server = importlib.import_module("server")

    def setUp(self):
        self.db = FakeDb()
        self.user = self.server.UserContext(user_id="user-a", db=self.db)

    def test_foreign_and_missing_chat_rejected_before_history_or_saves(self):
        payloads = (
            {"message": "Read the history"},
            {"message": "Send a message", "history": [{"role": "user", "content": "Earlier"}]},
            {"continue_after_tool": True,
             "history": [{"role": "tool", "name": "execute_command", "content": "{}"}]},
        )
        model = SimpleNamespace(models=SimpleNamespace(
            generate_content_stream=lambda **_kwargs: self.fail("Model was called")))
        with patch.object(self.server, "client", model):
            for chat_id in ("foreign", "missing"):
                for payload in payloads:
                    with self.subTest(chat_id=chat_id, payload=payload):
                        self.db.queries.clear()
                        with self.assertRaises(HTTPException) as caught:
                            self.server.stream_chat(
                                self.server.StreamChatPayload(chat_id=chat_id, **payload),
                                self.user,
                            )
                        self.assertEqual(caught.exception.status_code, 404)
                        self.assertEqual(caught.exception.detail, "Чат не найден")
                        self.assertEqual(self.db.queries, [
                            ("chats", {"id": chat_id, "user_id": "user-a"}, None)
                        ])
                        self.assertEqual(self.db.messages, [])

    def test_owned_chat_allows_message_and_tool_continuation(self):
        model = SimpleNamespace(models=SimpleNamespace(generate_content_stream=lambda **_kwargs: []))
        with patch.object(self.server, "client", model), patch.object(
            self.server, "StreamingResponse",
            side_effect=lambda generator, **_kwargs: SimpleNamespace(body_iterator=generator),
        ):
            response = self.server.stream_chat(
                self.server.StreamChatPayload(chat_id="own", message="Hello"),
                self.user,
            )
            list(response.body_iterator)
            self.assertEqual([(row["role"], row["content"]) for row in self.db.messages],
                             [("user", "Hello")])

            response = self.server.stream_chat(
                self.server.StreamChatPayload(
                    chat_id="own",
                    continue_after_tool=True,
                    history=[
                        self.server.MessageItem(role="user", content="Hello"),
                        self.server.MessageItem(role="tool", name="execute_command", content="{}"),
                    ],
                ), self.user,
            )
            list(response.body_iterator)
            self.assertEqual([(row["role"], row["content"]) for row in self.db.messages],
                             [("user", "Hello"), ("tool", "{}")])


if __name__ == "__main__":
    unittest.main()

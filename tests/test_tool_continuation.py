import asyncio
import importlib
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException


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
        self.chats = [{"id": "chat-1", "user_id": "user-1"}]
        self.messages = []

    def table(self, name):
        return FakeQuery(self, name)


class ToolContinuationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {
            "HOME": home,
            "API_KEY": "test-key",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "test-anon-key",
        }):
            cls.main = importlib.import_module("main")
            cls.server = importlib.import_module("server")

    def test_request_tool_result_answer_has_one_original_request(self):
        for temporary in (False, True):
            with self.subTest(temporary=temporary):
                db = FakeDb()
                user = self.server.UserContext("user-1", db)
                chat_id = None if temporary else "chat-1"
                history = [{"role": "user", "content": "Do task"}]
                seen_contents = []

                def generate_content_stream(**kwargs):
                    seen_contents.append(kwargs["contents"])
                    if len(seen_contents) == 1:
                        yield SimpleNamespace(function_calls=[SimpleNamespace(
                            name="execute_command", args={"command": "pwd"}, id="call-1"
                        )], text=None)
                    else:
                        yield SimpleNamespace(function_calls=None, text="Done")

                model = SimpleNamespace(models=SimpleNamespace(
                    generate_content_stream=generate_content_stream))
                with patch.object(self.server, "client", model), patch.object(
                    self.server, "StreamingResponse",
                    side_effect=lambda generator, **_kwargs: SimpleNamespace(body_iterator=generator),
                ):
                    first = self.main.build_stream_payload(history, chat_id, "test-model", temporary)
                    self.assertFalse(first["continue_after_tool"])
                    response, tasks = self.send(first, user)
                    self.assertIn(b'"tool_call"', b"".join(response.body_iterator))
                    asyncio.run(tasks())

                    history.extend([
                        {"role": "model", "content": "[tool call]", "name": "execute_command",
                         "args": {"command": "pwd"}},
                        {"role": "tool", "content": '{"output":"/work"}',
                         "name": "execute_command"},
                    ])
                    second = self.main.build_stream_payload(history, chat_id, "test-model", temporary)
                    self.assertTrue(second["continue_after_tool"])
                    self.assertEqual(second["message"], "")
                    response, tasks = self.send(second, user)
                    self.assertIn(b'Done', b"".join(response.body_iterator))
                    asyncio.run(tasks())

                for contents in seen_contents:
                    request_parts = [part.text for item in contents for part in item.parts
                                     if part.text == "Do task"]
                    self.assertEqual(request_parts, ["Do task"])
                if not temporary:
                    self.assertEqual([row["role"] for row in db.messages],
                                     ["user", "model", "tool", "model"])
                    self.assertEqual([row["content"] for row in db.messages if row["role"] == "user"],
                                     ["Do task"])
                    self.assertEqual([row["content"] for row in db.messages if row["role"] == "tool"],
                                     ['{"output":"/work"}'])

    def send(self, data, user):
        tasks = BackgroundTasks()
        payload = self.server.StreamChatPayload(**data)
        return self.server.stream_chat(payload, tasks, user), tasks

    def test_continuation_requires_tool_result(self):
        user = self.server.UserContext("user-1", FakeDb())
        for data in ({"continue_after_tool": True},
                     {"continue_after_tool": True, "message": "Do task",
                      "history": [{"role": "tool", "content": "{}"}]}):
            with self.subTest(data=data), self.assertRaises(HTTPException) as error:
                self.send(data, user)
            self.assertEqual(error.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()

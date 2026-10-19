import importlib
import base64
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from google.genai import types


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

    def setUp(self):
        # These tests isolate history/transport; subscription guards have HTTP tests.
        guard = patch.object(self.server, "require_subscription", return_value={"features": list(self.server.TOOLS)})
        guard.start()
        self.addCleanup(guard.stop)
        budget = patch.object(self.server, "reserve_request")
        budget.start()
        self.addCleanup(budget.stop)

    def test_legacy_large_row_outside_context_does_not_block_resume(self):
        db = FakeDb()
        db.messages = [{"chat_id": "chat-1", "role": "user", "content": "x" * 40000}]
        db.messages += [{"chat_id": "chat-1", "role": "user", "content": str(index)} for index in range(24)]
        result = self.server.build_history_from_db(db, "chat-1")
        self.assertEqual(len(result), 20)
        self.assertNotIn("x" * 40000, str(result))

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
                    first = self.main.build_stream_payload(history, chat_id, "gemini-3.5-flash-lite", temporary)
                    self.assertFalse(first["continue_after_tool"])
                    response = self.send(first, user)
                    self.assertIn(b'"tool_call"', b"".join(response.body_iterator))

                    history.extend([
                        {"role": "model", "content": "[tool call]", "name": "execute_command",
                         "args": {"command": "pwd"}},
                        {"role": "tool", "content": '{"output":"/work"}',
                         "name": "execute_command"},
                    ])
                    second = self.main.build_stream_payload(history, chat_id, "gemini-3.5-flash-lite", temporary)
                    self.assertTrue(second["continue_after_tool"])
                    self.assertEqual(second["message"], "")
                    response = self.send(second, user)
                    self.assertIn(b'Done', b"".join(response.body_iterator))

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
        payload = self.server.StreamChatPayload(**data)
        return self.server.stream_chat(payload, user)

    def test_continuation_requires_tool_result(self):
        user = self.server.UserContext("user-1", FakeDb())
        for data in ({"continue_after_tool": True},
                     {"continue_after_tool": True, "message": "Do task",
                      "history": [{"role": "tool", "content": "{}"}]}):
            with self.subTest(data=data), self.assertRaises(HTTPException) as error:
                self.send(data, user)
            self.assertEqual(error.exception.status_code, 400)

    def test_reopened_chat_keeps_older_db_context_after_tool(self):
        db = FakeDb()
        db.messages.extend([
            {"chat_id": "chat-1", "role": "user", "content": "Remember amber"},
            {"chat_id": "chat-1", "role": "model", "content": "I will remember amber"},
        ])
        user = self.server.UserContext("user-1", db)
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
            # A reopened client has no local copy of the older exchange.
            history = [{"role": "user", "content": "Run pwd"}]
            response = self.send(
                self.main.build_stream_payload(history, "chat-1", "gemini-3.5-flash-lite", False), user
            )
            list(response.body_iterator)
            history.extend([
                {"role": "model", "content": "[tool call]", "name": "execute_command",
                 "args": {"command": "pwd"}},
                {"role": "tool", "content": '{"output":"/work"}',
                 "name": "execute_command"},
            ])
            response = self.send(
                self.main.build_stream_payload(history, "chat-1", "gemini-3.5-flash-lite", False), user
            )
            list(response.body_iterator)

        parts = [part for item in seen_contents[1] for part in item.parts]
        texts = [part.text for part in parts if part.text is not None]
        self.assertEqual(texts, ["Remember amber", "I will remember amber", "Run pwd"])
        self.assertEqual(len([part for part in parts if part.function_call is not None]), 1)
        self.assertEqual(len([part for part in parts if part.function_response is not None]), 1)

    def test_multiple_tool_calls_return_in_order_with_ids(self):
        for temporary in (False, True):
            with self.subTest(temporary=temporary):
                db = FakeDb()
                user = self.server.UserContext("user-1", db)
                chat_id = None if temporary else "chat-1"
                history = [{"role": "user", "content": "Run both"}]
                seen_contents = []

                def generate_content_stream(**kwargs):
                    seen_contents.append(kwargs["contents"])
                    if len(seen_contents) == 1:
                        yield SimpleNamespace(function_calls=[SimpleNamespace(
                            name="execute_command", args={"command": "pwd"}, id="call-1"
                        )], text=None)
                        yield SimpleNamespace(function_calls=[SimpleNamespace(
                            name="execute_command", args={"command": "date"}, id="call-2"
                        )], text=None)
                    else:
                        yield SimpleNamespace(function_calls=None, text="Both done")

                model = SimpleNamespace(models=SimpleNamespace(
                    generate_content_stream=generate_content_stream))
                with patch.object(self.server, "client", model), patch.object(
                    self.server, "StreamingResponse",
                    side_effect=lambda generator, **_kwargs: SimpleNamespace(body_iterator=generator),
                ), patch.object(self.main, "handle_execute_command", side_effect=[
                    '{"output":"/work"}', '{"output":"today"}'
                ]) as execute:
                    first = self.main.build_stream_payload(history, chat_id, "gemini-3.5-flash-lite", temporary)
                    response = self.send(first, user)
                    stream = SimpleNamespace(iter_lines=lambda: response.body_iterator)
                    events = list(self.main.iter_stream_events(stream))
                    calls = [event for event in events if event["type"] == "tool_call"]
                    self.assertEqual([call["call_id"] for call in calls], ["call-1", "call-2"])
                    self.main.execute_tool_calls(calls, history, "/work")
                    self.assertEqual(execute.call_count, 2)
                    second = self.main.build_stream_payload(history, chat_id, "gemini-3.5-flash-lite", temporary)
                    response = self.send(second, user)
                    self.assertIn(b"Both done", b"".join(response.body_iterator))

                self.assertEqual([entry["role"] for entry in history],
                                 ["user", "model", "model", "tool", "tool"])
                self.assertEqual([entry["call_id"] for entry in history[1:]],
                                 ["call-1", "call-2", "call-1", "call-2"])
                calls_content = [content for content in seen_contents[1] if content.role == "model"]
                responses_content = [content for content in seen_contents[1] if content.role == "user"
                                     and content.parts[0].function_response is not None]
                self.assertEqual([[part.function_call.id for part in content.parts]
                                  for content in calls_content], [["call-1", "call-2"]])
                self.assertEqual([[part.function_response.id for part in content.parts]
                                  for content in responses_content], [["call-1", "call-2"]])
                if not temporary:
                    self.assertEqual([row["role"] for row in db.messages],
                                     ["user", "model", "model", "tool", "tool", "model"])
                    self.assertEqual([row["content"] for row in db.messages if row["role"] == "tool"],
                                     ['{"output":"/work"}', '{"output":"today"}'])

    def test_gemini_3_tool_signature_survives_stream_and_continuation(self):
        signature = b"signed-model-thought"
        history = [{"role": "user", "content": "Run pwd"}]
        seen_contents = []

        def generate_content_stream(**kwargs):
            seen_contents.append(kwargs["contents"])
            if len(seen_contents) == 1:
                part = types.Part(
                    function_call=types.FunctionCall(
                        name="execute_command", args={"command": "pwd"}, id="call-1"),
                    thought_signature=signature,
                )
                yield SimpleNamespace(candidates=[SimpleNamespace(
                    content=types.Content(role="model", parts=[part])
                )], function_calls=[part.function_call], text=None)
            else:
                yield SimpleNamespace(function_calls=None, text="Done")

        model = SimpleNamespace(models=SimpleNamespace(generate_content_stream=generate_content_stream))
        with patch.object(self.server, "client", model), patch.object(
            self.server, "StreamingResponse",
            side_effect=lambda generator, **_kwargs: SimpleNamespace(body_iterator=generator),
        ), patch.object(self.main, "handle_execute_command", return_value='{"output":"/work"}'):
            first = self.send(self.main.build_stream_payload(history, None,
                                   "gemini-3.5-flash-lite", True),
                              self.server.UserContext("user-1", FakeDb()))
            events = list(self.main.iter_stream_events(
                SimpleNamespace(iter_lines=lambda: first.body_iterator)
            ))
            calls = [event for event in events if event["type"] == "tool_call"]
            self.assertEqual(calls[0]["thought_signature"],
                             base64.b64encode(signature).decode("ascii"))
            self.main.execute_tool_calls(calls, history, "/work")
            second = self.send(self.main.build_stream_payload(history, None,
                                    "gemini-3.5-flash-lite", True),
                               self.server.UserContext("user-1", FakeDb()))
            self.assertIn(b"Done", b"".join(second.body_iterator))

        call_part = seen_contents[1][1].parts[0]
        self.assertEqual(call_part.thought_signature, signature)
        self.assertEqual(call_part.function_call.id, "call-1")

    def test_large_tool_batch_keeps_every_result(self):
        history = [{"role": "user", "content": "Run batch"}]
        calls = [{"type": "tool_call", "name": "execute_command",
                  "args": {"command": str(index)}, "call_id": f"call-{index}"}
                 for index in range(21)]
        with patch.object(self.main, "handle_execute_command",
                          side_effect=[f'{{"output":"{index}"}}' for index in range(21)]):
            self.main.execute_tool_calls(calls, history, "/work")
        trimmed = self.main.trim_history(history)
        self.assertEqual(len(trimmed), 43)
        items = [self.server.MessageItem(**item) for item in trimmed]
        contents = self.server.build_history_from_client(items)
        self.assertEqual(len(contents[1].parts), 21)
        self.assertEqual(len(contents[2].parts), 21)
        self.assertEqual(contents[2].parts[-1].function_response.response,
                         {"output": "20"})

    def test_turn_limit_persists_final_batch_without_another_model_call(self):
        db = FakeDb()
        user = self.server.UserContext("user-1", db)
        self.server.save_message_to_db(db, "chat-1", "user", "Run task")
        self.server.save_message_to_db(db, "chat-1", "model", "call", "execute_command", {"command": "fixture"})
        history = [{"role": "user", "content": "Run task"},
                   {"role": "model", "content": "call", "name": "execute_command",
                    "args": {"command": "fixture"}, "call_id": "final-call"},
                   {"role": "tool", "name": "execute_command", "content": '{"stdout":"final result"}',
                    "call_id": "final-call"}]
        payload = self.main.build_stream_payload(history, "chat-1", "gemini-3.5-flash-lite", False, end_tool_turn=True)
        self.assertEqual(payload["supported_tools"], [])
        generate = Mock(side_effect=AssertionError("Unexpected model call"))
        model = SimpleNamespace(models=SimpleNamespace(generate_content_stream=generate))
        with patch.object(self.server, "client", model), patch.object(
            self.server, "StreamingResponse", side_effect=lambda generator, **_: SimpleNamespace(body_iterator=generator)
        ):
            events = list(self.send(payload, user).body_iterator)
        generate.assert_not_called()
        self.assertIn(b'"type": "text"', b"".join(events))
        self.assertEqual([row["content"] for row in db.messages if row["role"] == "tool"],
                         ['{"stdout":"final result"}'])
        restored = self.server.build_history_from_db(db, "chat-1")
        self.assertIsNone(restored[-1].parts[0].function_call)
        self.assertEqual(restored[-2].parts[0].function_response.response, {"stdout": "final result"})

    def test_end_tool_turn_requires_a_continuation(self):
        with self.assertRaises(HTTPException) as raised:
            self.server.stream_chat(self.server.StreamChatPayload(message="hello", end_tool_turn=True),
                                    self.server.UserContext("user-1", FakeDb()))
        self.assertEqual(raised.exception.status_code, 400)

    def test_reopened_chat_restores_saved_tool_calls_and_responses(self):
        db = FakeDb()
        db.messages.extend([
            {"chat_id": "chat-1", "role": "user", "content": "Run both"},
            {"chat_id": "chat-1", "role": "model", "content": "[tool call]",
             "name": "execute_command", "args": {"command": "pwd"}},
            {"chat_id": "chat-1", "role": "model", "content": "[tool call]",
             "name": "read_local_files", "args": {"filepaths": ["a.txt"]}},
            {"chat_id": "chat-1", "role": "tool", "content": '{"output":"/work"}',
             "name": "execute_command"},
            {"chat_id": "chat-1", "role": "tool", "content": '{"files":{"a.txt":"hello"}}',
             "name": "read_local_files"},
            {"chat_id": "chat-1", "role": "model", "content": "Both done"},
        ])
        seen_contents = []

        def generate_content_stream(**kwargs):
            seen_contents.append(kwargs["contents"])
            yield SimpleNamespace(function_calls=None, text="Next answer")

        model = SimpleNamespace(models=SimpleNamespace(
            generate_content_stream=generate_content_stream))
        user = self.server.UserContext("user-1", db)
        with patch.object(self.server, "client", model), patch.object(
            self.server, "StreamingResponse",
            side_effect=lambda generator, **_kwargs: SimpleNamespace(body_iterator=generator),
        ):
            response = self.send({
                "chat_id": "chat-1", "message": "What happened?", "model_name": "gemini-3.5-flash-lite"
            }, user)
            self.assertIn(b"Next answer", b"".join(response.body_iterator))

        contents = seen_contents[0]
        self.assertEqual([content.role for content in contents],
                         ["user", "model", "user", "model", "user"])
        calls = [part.function_call for part in contents[1].parts]
        results = [part.function_response for part in contents[2].parts]
        self.assertEqual([(call.name, call.args) for call in calls], [
            ("execute_command", {"command": "pwd"}),
            ("read_local_files", {"filepaths": ["a.txt"]}),
        ])
        self.assertEqual([(result.name, result.response) for result in results], [
            ("execute_command", {"output": "/work"}),
            ("read_local_files", {"status": "redacted",
                                  "message": "Результат чтения файлов не сохраняется"}),
        ])
        self.assertEqual(contents[-1].parts[0].text, "What happened?")

    def test_read_result_is_used_for_current_turn_but_not_saved_or_replayed(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        (Path(workspace.name) / "notes.txt").write_text("private content", encoding="utf-8")
        db = FakeDb()
        user = self.server.UserContext("user-1", db)
        history = [{"role": "user", "content": "Read file"}]
        seen_contents = []

        def generate_content_stream(**kwargs):
            seen_contents.append(kwargs["contents"])
            if len(seen_contents) == 1:
                yield SimpleNamespace(function_calls=[SimpleNamespace(
                    name="read_local_files", args={"filepaths": ["notes.txt"]}, id="read-1"
                )], text=None)
            else:
                yield SimpleNamespace(function_calls=None, text="Done")

        model = SimpleNamespace(models=SimpleNamespace(generate_content_stream=generate_content_stream))
        with patch.object(self.server, "client", model), patch.object(
            self.server, "StreamingResponse",
            side_effect=lambda generator, **_kwargs: SimpleNamespace(body_iterator=generator),
        ), patch.object(self.main.console, "print"), patch("builtins.input", return_value="y"):
            first = self.send(self.main.build_stream_payload(history, "chat-1", "gemini-3.5-flash-lite", False), user)
            events = list(self.main.iter_stream_events(
                SimpleNamespace(iter_lines=lambda: first.body_iterator)
            ))
            self.main.execute_tool_calls([event for event in events if event["type"] == "tool_call"],
                                         history, workspace.name)
            second = self.send(self.main.build_stream_payload(history, "chat-1", "gemini-3.5-flash-lite", False), user)
            list(second.body_iterator)

        response = seen_contents[1][-1].parts[0].function_response
        self.assertEqual(response.response, {"notes.txt": "private content"})
        stored = [row["content"] for row in db.messages if row["role"] == "tool"]
        self.assertEqual(stored, [self.server.REDACTED_READ_RESULT])
        next(row for row in db.messages if row["role"] == "tool")["content"] = \
            '{"notes.txt":"legacy secret"}'
        replayed = self.server.build_history_from_db(db, "chat-1")
        responses = [part.function_response for item in replayed for part in item.parts
                     if part.function_response is not None]
        self.assertEqual(responses[0].response["status"], "redacted")
        replayed_text = str(replayed)
        self.assertNotIn("private content", replayed_text)
        self.assertNotIn("legacy secret", replayed_text)


if __name__ == "__main__":
    unittest.main()

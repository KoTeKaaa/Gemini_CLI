"""Stream integration guards: reservation ownership and durable context recovery."""
import importlib
import json
import os
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from tests.test_chat_stream_ownership import FakeDb


class ServerHistoryRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {"API_KEY": "fixture", "SUPABASE_URL": "https://example.supabase.co",
                                     "SUPABASE_ANON_KEY": "fixture"}):
            cls.server = importlib.import_module("server")

    def setUp(self):
        self.db = FakeDb()
        self.user = self.server.UserContext(user_id="user-a", db=self.db)
        self.turn, self.request = uuid4(), uuid4()
        self.store = Mock()
        self.store.read.return_value = []
        self.store.metadata.return_value = {}
        self.order = []
        def append(_chat, rows, **kwargs):
            self.order.append("append")
            return kwargs["start"] + len(rows)
        self.store.append.side_effect = append
        def reserve(*_args, **_kwargs):
            self.order.append("reserve")
        self.budget = Mock(side_effect=reserve)
        def generate(*_args, **_kwargs):
            self.order.append("provider")
            yield {"type": "text", "content": "answer"}
        self.provider = Mock(side_effect=generate)
        patches = (
            patch.object(self.server, "HistoryStore", return_value=self.store),
            patch.object(self.server, "require_subscription", return_value={"features": list(self.server.TOOLS)}),
            patch.object(self.server, "reserve_request", self.budget),
            patch.object(self.server, "stream_events", self.provider),
            patch.object(self.server, "StreamJob", side_effect=lambda source, *_args:
                         SimpleNamespace(source=source, cancelled=Event())),
            patch.object(self.server, "StreamingResponse", side_effect=lambda job, **_kwargs:
                         SimpleNamespace(body_iterator=job.source)),
        )
        for context in patches:
            context.start()
            self.addCleanup(context.stop)

    def stream(self, **kwargs):
        payload = self.server.StreamChatPayload(chat_id="own", turn_id=self.turn,
            request_id=self.request, **kwargs)
        return list(self.server.stream_chat(payload,self.user).body_iterator)

    def test_identified_stream_reserves_before_writes_and_finishes_own_request(self):
        chunks = self.stream(message="question")
        self.assertEqual(self.order, ["reserve", "append", "provider", "append"])
        self.assertTrue(any(b"answer" in chunk for chunk in chunks))
        self.store.finish.assert_called_once_with("own",self.request,"completed")
        self.store.read.assert_called_once_with("own")
        self.store.metadata.assert_called_once_with("own")
        self.assertEqual(self.db.queries[0],("chats",{"id":"own","user_id":"user-a"},None))
        first, final = self.store.append.call_args_list
        self.assertEqual(first.args[1][0]["role"],"user")
        self.assertEqual(first.kwargs["start"],0)
        self.assertEqual(final.kwargs["start"],1)
        self.assertEqual(final.kwargs["turn_id"],self.turn)
        self.assertEqual(final.kwargs["request_id"],self.request)

    def test_duplicate_cannot_finalize_original_running_request(self):
        # The existing row belongs to an original generator still running elsewhere.
        self.store.read.return_value = [{"role":"user","content":"question","turn_id":str(self.turn),
                                         "request_id":str(self.request),"status":"running"}]
        self.budget.side_effect = HTTPException(409,"duplicate")
        chunks = self.stream(message="question")
        self.assertTrue(any(b"duplicate" in chunk for chunk in chunks))
        self.store.append.assert_not_called()
        self.store.finish.assert_not_called()
        self.provider.assert_not_called()
        self.assertEqual(self.store.read.return_value[0]["status"],"running")

    def test_static_tool_limit_saves_results_without_gemini_budget_or_provider(self):
        self.budget.side_effect = HTTPException(429,"exhausted")
        history = [
            {"role":"user","content":"question","turn_id":str(self.turn)},
            {"role":"model","content":"call","name":"execute_command","args":{},"call_id":"tool-1"},
            {"role":"tool","content":"{}","name":"execute_command","call_id":"tool-1"},
        ]
        chunks = self.stream(continue_after_tool=True,end_tool_turn=True,history=history)
        self.budget.assert_not_called()
        self.provider.assert_not_called()
        self.assertEqual(self.store.append.call_args_list[0].args[1][0]["role"],"tool")
        self.assertEqual(self.store.append.call_args_list[-1].args[1][0]["role"],"model")
        self.store.finish.assert_called_once_with("own",self.request,"completed")
        events = [json.loads(chunk.decode().split("data: ",1)[1]) for chunk in chunks]
        self.assertEqual([event["type"] for event in events],["text"])

    def test_persisted_summary_is_authoritative_over_client_history(self):
        boundary = str(uuid4())
        self.store.read.return_value = [
            {"id":str(uuid4()),"role":"user","content":"discarded prefix"},
            {"id":boundary,"role":"model","content":"discarded answer"},
            {"id":str(uuid4()),"role":"user","content":"retained turn"},
        ]
        self.store.metadata.return_value = {"summary":"trusted summary","summary_boundary":boundary}
        with patch.object(self.server,"to_gemini",side_effect=lambda rows: rows):
            self.stream(message="new question",history=[{"role":"user","content":"client replacement"}])
        sent = self.provider.call_args.kwargs["contents"]
        self.assertEqual([row["content"] for row in sent],
                         ["Сводка предыдущего диалога:\ntrusted summary","retained turn","new question"])


if __name__ == "__main__":
    unittest.main()

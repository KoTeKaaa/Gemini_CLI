import asyncio
import importlib
import os
from unittest.mock import patch
import threading
import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from gemini_cli.server.limits import BodyLimit, GenerationSlots, StreamJob


class ServerLimitsTest(unittest.TestCase):
    def test_body_limit_counts_chunks_without_content_length(self):
        called, sent = [], []
        async def app(*_args):
            called.append(True)
        chunks = iter([{"type": "http.request", "body": b"123", "more_body": True},
                       {"type": "http.request", "body": b"456", "more_body": False}])
        async def receive():
            return next(chunks)
        async def send(message):
            sent.append(message)
        asyncio.run(BodyLimit(app, 5)({"type": "http"}, receive, send))
        self.assertEqual(called, [])
        self.assertEqual(sent[0]["status"], 413)

    def test_slots_isolate_users_and_release(self):
        slots = GenerationSlots(total=2)
        slots.acquire("a", 1)
        with self.assertRaises(HTTPException):
            slots.acquire("a", 1)
        slots.acquire("b", 2)
        with self.assertRaises(HTTPException):
            slots.acquire("c", 1)
        slots.release("a")
        slots.release("b")
        self.assertEqual(slots.active, {})

    def test_cancelled_consumer_does_not_leave_worker_or_slot(self):
        slots, finished = GenerationSlots(), threading.Event()
        def source():
            try:
                while True:
                    yield b"x"
            finally:
                finished.set()
        job = StreamJob(source(), "a", 1, slots=slots)
        stream = iter(job)
        self.assertEqual(next(stream), b"x")
        stream.close()
        self.assertTrue(finished.wait(2))
        # The generator's finally precedes the slot release by a few instructions.
        with slots.lock:
            pass
        for _ in range(100):
            if not slots.active:
                break
            threading.Event().wait(.01)
        self.assertEqual(slots.active, {})

    def test_payload_limits_and_unknown_models_tools(self):
        with patch.dict(os.environ, {"API_KEY": "fixture", "SUPABASE_URL": "https://example.com",
                                     "SUPABASE_ANON_KEY": "fixture"}):
            importlib.import_module("server")
        from server import StreamChatPayload
        for payload in ({"message": "x" * 32769}, {"model_name": "forged"},
                        {"supported_tools": ["forged"]},
                        {"history": [{"role": "user", "content": "x"}] * 1001}):
            with self.subTest(payload=list(payload)), self.assertRaises(ValidationError):
                StreamChatPayload(**payload)

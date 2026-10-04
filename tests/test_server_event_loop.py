import importlib
import inspect
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch


class SlowChatsQuery:
    def __init__(self, started, release):
        self.started = started
        self.release = release

    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        self.started.set()
        if not self.release.wait(5):
            raise TimeoutError("database query was not released")
        return SimpleNamespace(data=[])


class EventLoopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            "API_KEY": "test-key",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "test-anon-key",
        }):
            cls.server = importlib.import_module("server")

    def test_stream_completes_while_chat_query_is_slow(self):
        server = self.server
        for handler in (server.get_current_user, server.get_chats,
                        server.create_chat, server.delete_chat, server.stream_chat):
            self.assertFalse(inspect.iscoroutinefunction(handler))

        started = threading.Event()
        release = threading.Event()
        db = SimpleNamespace(table=lambda _name: SlowChatsQuery(started, release))
        user = server.UserContext("user", db)
        model = SimpleNamespace(models=SimpleNamespace(generate_content_stream=lambda **_kwargs: [
            SimpleNamespace(function_calls=None, text="ready")
        ]))
        try:
            with patch.object(server, "client", model), patch.object(
                server, "StreamingResponse",
                side_effect=lambda generator, **_kwargs: SimpleNamespace(body_iterator=generator),
            ), ThreadPoolExecutor(max_workers=2) as pool:
                slow_request = pool.submit(server.get_chats, user)
                try:
                    self.assertTrue(started.wait(2))
                    stream_request = pool.submit(
                        lambda: list(server.stream_chat(
                            server.StreamChatPayload(message="hello"), user
                        ).body_iterator)
                    )
                    chunks = stream_request.result(timeout=2)
                    self.assertIn(b'"content": "ready"', b"".join(chunks))
                finally:
                    release.set()
                self.assertEqual(slow_request.result(timeout=2), [])
        finally:
            release.set()

    def test_other_auth_request_completes_while_auth_is_slow(self):
        server = self.server
        started = threading.Event()
        release = threading.Event()

        def create_client(_url, _key, options):
            token = options.headers["Authorization"].removeprefix("Bearer ")

            def get_user(_token):
                if token == "slow":
                    started.set()
                    if not release.wait(5):
                        raise TimeoutError("auth request was not released")
                return SimpleNamespace(user=SimpleNamespace(id=token))

            return SimpleNamespace(auth=SimpleNamespace(get_user=get_user))

        with patch.object(server, "create_client", side_effect=create_client), \
                ThreadPoolExecutor(max_workers=2) as pool:
            slow_request = pool.submit(server.get_current_user, "Bearer slow")
            try:
                self.assertTrue(started.wait(2))
                quick_request = pool.submit(server.get_current_user, "Bearer quick")
                self.assertEqual(quick_request.result(timeout=2).user_id, "quick")
            finally:
                release.set()
            self.assertEqual(slow_request.result(timeout=2).user_id, "slow")


if __name__ == "__main__":
    unittest.main()

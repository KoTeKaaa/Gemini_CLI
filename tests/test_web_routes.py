import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import Header, HTTPException
from pydantic import ValidationError
from gemini_cli.server.web_routes import SearchPayload
from gemini_cli.server.web_routes import create_web_router


class WebRoutesTest(unittest.TestCase):
    def make_client(self, key="fixture", limit=1):
        def get_user(authorization: str | None = Header(None)):
            if not authorization:
                raise HTTPException(401)
            return SimpleNamespace(user_id=authorization)
        self.adapter = Mock(return_value={"status": "ok", "data": {"results": []}})
        router = create_web_router(get_user, api_key=key,
                                   search_adapter=self.adapter, search_limit=limit)
        route = next(route for route in router.routes if route.path == "/tools/web/search")
        self.assertIs(route.dependant.dependencies[0].call, get_user)
        def request(query="q", user="user-a", **kwargs):
            identity = get_user(user)
            return route.endpoint(SearchPayload(query=query, **kwargs), identity)
        return request

    def test_auth_validation_and_per_user_limits(self):
        request = self.make_client()
        with self.assertRaises(HTTPException):
            request(user=None)
        with self.assertRaises(ValidationError):
            request(max_results=6)
        self.adapter.assert_not_called()
        for user, status in (("user-a", "ok"), ("user-a", "error"), ("user-b", "ok")):
            self.assertEqual(request(user=user)["status"], status)
        self.assertEqual(self.adapter.call_count, 2)

    def test_missing_key_keeps_server_usable(self):
        request = self.make_client(key=None)
        self.assertEqual(request()["error"]["code"], "unavailable")
        self.adapter.assert_not_called()

    def test_slow_search_does_not_block_another_request(self):
        started, release = Event(), Event()
        def adapter(query, *args, **kwargs):
            if query == "slow":
                started.set()
                release.wait(5)
            return {"status": "ok"}
        request = self.make_client()
        self.adapter.side_effect = adapter
        with ThreadPoolExecutor() as pool:
            slow = pool.submit(request, "slow", "a")
            try:
                self.assertTrue(started.wait(2))
                fast = pool.submit(request, "fast", "b")
                self.assertEqual(fast.result(timeout=2)["status"], "ok")
            finally:
                release.set()
            self.assertEqual(slow.result(timeout=2)["status"], "ok")

import importlib
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from gemini_cli.server.subscriptions import require_subscription


def rights_row(**changes):
    return dict(user_id="user-a", status="active", expires_at="2099-01-01T00:00:00+00:00",
                models=["gemini-3.5-flash-lite"], features=[], **changes)


class SubscriptionTest(unittest.TestCase):
    def setUp(self):
        self.query = Mock()
        self.query.select.return_value = self.query
        self.query.eq.return_value = self.query
        self.query.execute.return_value = SimpleNamespace(data=[rights_row()])
        self.user = SimpleNamespace(user_id="user-a", db=Mock())
        self.user.db.table.return_value = self.query

    def test_missing_expired_revoked_and_failed_read_deny(self):
        for rows, code in (([], 403), ([{**rights_row(), "status": "revoked"}], 403),
                           ([{**rights_row(), "expires_at": "2000-01-01T00:00:00Z"}], 403),
                           ([{"status": "active"}], 503)):
            self.query.execute.return_value = SimpleNamespace(data=rows)
            with self.subTest(rows=rows), self.assertRaises(HTTPException) as caught:
                require_subscription(self.user)
            self.assertEqual(caught.exception.status_code, code)
        self.query.execute.side_effect = RuntimeError("private failure")
        with self.assertRaises(HTTPException) as caught:
            require_subscription(self.user)
        self.assertNotIn("private", caught.exception.detail)

    def test_model_features_and_revocation_are_rechecked(self):
        require_subscription(self.user, model="gemini-3.5-flash-lite")
        for kwargs in ({"model": "forged"}, {"features": ["execute_command"]}):
            with self.assertRaises(HTTPException):
                require_subscription(self.user, **kwargs)
        self.query.execute.return_value.data[0]["status"] = "suspended"
        with self.assertRaises(HTTPException):
            require_subscription(self.user)

    def test_direct_http_cannot_bypass_subscription(self):
        with patch.dict(os.environ, {"API_KEY": "fixture", "SUPABASE_URL": "https://example.com",
                                     "SUPABASE_ANON_KEY": "fixture"}):
            server = importlib.import_module("server")
        server.app.dependency_overrides[server.get_current_user] = lambda: self.user
        try:
            self.query.execute.return_value.data = []
            with TestClient(server.app) as http:
                for path, payload in (("/chats", {"title": "x"}),
                                      ("/chat/stream", {"message": "x"}),
                                      ("/tools/web/search", {"query": "x"})):
                    self.assertEqual(http.post(path, json=payload).status_code, 403)
                self.assertEqual(http.get("/chats").status_code, 403)
        finally:
            server.app.dependency_overrides.clear()

    def test_revocation_between_request_and_provider(self):
        with patch.dict(os.environ, {"API_KEY": "fixture", "SUPABASE_URL": "https://example.com",
                                     "SUPABASE_ANON_KEY": "fixture"}):
            server = importlib.import_module("server")
        model = Mock()
        with patch.object(server, "client", model), patch.object(
            server, "StreamingResponse", side_effect=lambda body, **kw: body
        ):
            body = server.stream_chat(server.StreamChatPayload(message="x", supported_tools=[]), self.user)
            self.query.execute.return_value.data[0]["status"] = "revoked"
            self.assertIn(b'error', b''.join(body))
        model.models.generate_content_stream.assert_not_called()

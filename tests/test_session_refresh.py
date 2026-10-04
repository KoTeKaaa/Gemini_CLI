import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from supabase_auth.errors import AuthApiError


class SessionRefreshTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"HOME": home}):
            cls.app = importlib.import_module("main")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.session_file = Path(self.directory.name) / "session.json"
        self.session_file.write_text(json.dumps({
            "access_token": "expired", "refresh_token": "old-refresh",
        }), encoding="utf-8")
        patcher = patch.object(self.app, "SESSION_FILE", str(self.session_file))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = self.app.GeminiAPIClient("https://example.com")
        self.client.set_token("expired")

    def test_expired_token_retries_chat_list_and_stream(self):
        refreshed = Mock(status_code=200)
        refreshed.json.return_value = {
            "access_token": "fresh", "refresh_token": "new-refresh",
        }
        unauthorized = Mock(status_code=401)
        success = Mock(status_code=200)
        success.json.return_value = []
        with patch.object(self.app.requests, "get", side_effect=[unauthorized, success]) as get, \
                patch.object(self.app.requests, "post", return_value=refreshed) as post:
            self.assertEqual(self.client.get_chats(), [])
        self.assertEqual(get.call_args_list[0].kwargs["headers"],
                         {"Authorization": "Bearer expired"})
        self.assertEqual(get.call_args_list[1].kwargs["headers"],
                         {"Authorization": "Bearer fresh"})
        self.assertEqual(post.call_args.args[0], "https://example.com/auth/refresh")
        self.assertEqual(post.call_args.kwargs["json"], {"refresh_token": "old-refresh"})
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertEqual(json.loads(self.session_file.read_text())["refresh_token"], "new-refresh")
        unauthorized.close.assert_called_once()

        self.client.set_token("expired")
        with patch.object(self.app.requests, "post", side_effect=[
            unauthorized, refreshed, success,
        ]) as post:
            self.assertIs(self.client.stream_chat({"message": "hello"}), success)
        self.assertEqual(post.call_args_list[0].kwargs["headers"],
                         {"Authorization": "Bearer expired"})
        self.assertEqual(post.call_args_list[2].kwargs["headers"],
                         {"Authorization": "Bearer fresh"})
        self.assertTrue(post.call_args_list[2].kwargs["stream"])

    def test_invalid_refresh_removes_session_and_reauthenticates(self):
        unauthorized = Mock(status_code=401)
        with patch.object(self.app.requests, "post", return_value=unauthorized), \
                patch.object(self.client, "login", side_effect=lambda: self.client.set_token("login-token")) as login, \
                patch.object(self.app.console, "print"):
            self.assertTrue(self.client._renew_session())
        login.assert_called_once()
        self.assertFalse(self.session_file.exists())
        self.assertEqual(self.client.token, "login-token")

    def test_temporary_refresh_failure_keeps_session(self):
        unavailable = Mock(status_code=503)
        with patch.object(self.app.requests, "post", return_value=unavailable), \
                patch.object(self.client, "login") as login, \
                patch.object(self.app.console, "print"):
            self.assertFalse(self.client._renew_session())
        login.assert_not_called()
        self.assertTrue(self.session_file.exists())

    def test_server_rotates_refresh_token_and_reports_failures(self):
        with patch.dict(os.environ, {
            "API_KEY": "test-key", "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "test-anon-key",
        }):
            sys.modules.pop("server", None)
            server = importlib.import_module("server")

        session = Mock()
        session.model_dump.return_value = {
            "access_token": "fresh", "refresh_token": "rotated",
        }
        auth = SimpleNamespace(refresh_session=Mock(return_value=SimpleNamespace(session=session)))
        with patch.object(server, "create_client", return_value=SimpleNamespace(auth=auth)):
            result = server.refresh_user_session(server.RefreshPayload(refresh_token="old"))
        self.assertEqual(result["refresh_token"], "rotated")
        auth.refresh_session.assert_called_once_with("old")

        auth.refresh_session.side_effect = ValueError("network down")
        with patch.object(server, "create_client", return_value=SimpleNamespace(auth=auth)), \
                patch("builtins.print"):
            with self.assertRaises(HTTPException) as error:
                server.refresh_user_session(server.RefreshPayload(refresh_token="old"))
        self.assertEqual(error.exception.status_code, 503)

        auth.refresh_session.side_effect = AuthApiError("invalid token", 400, None)
        with patch.object(server, "create_client", return_value=SimpleNamespace(auth=auth)), \
                patch("builtins.print"):
            with self.assertRaises(HTTPException) as error:
                server.refresh_user_session(server.RefreshPayload(refresh_token="old"))
        self.assertEqual(error.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()

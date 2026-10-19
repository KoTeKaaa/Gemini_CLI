import importlib
import os
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from gemini_cli.server.admin.accounts import invite_account


class ClosedRegistrationTest(unittest.TestCase):
    def test_signup_never_calls_provider(self):
        with patch.dict(os.environ, {"API_KEY": "fixture", "SUPABASE_URL": "https://example.com",
                                     "SUPABASE_ANON_KEY": "fixture"}):
            server = importlib.import_module("server")
        with patch.object(server, "create_client") as provider, self.assertRaises(HTTPException) as caught:
            server.signup_user(server.LoginPayload(email="a@example.com", password="x"))
        self.assertEqual(caught.exception.status_code, 403)
        provider.assert_not_called()

    def test_invitation_uses_server_adapter_and_does_not_enumerate(self):
        db = Mock()
        with patch.dict(os.environ, {"ADMIN_ORIGIN": "https://panel.test"}), patch(
            "gemini_cli.server.admin.accounts.admin_client", return_value=db
        ):
            success = invite_account("a@example.com")
            db.auth.admin.invite_user_by_email.assert_called_once_with("a@example.com", options={
                "redirect_to": "https://panel.test/account/confirm"})
            db.auth.admin.invite_user_by_email.side_effect = RuntimeError("private user exists")
            failure = invite_account("a@example.com")
        self.assertEqual(success, failure)
        self.assertNotIn("private", str(failure))

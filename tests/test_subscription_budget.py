import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

from fastapi import HTTPException

from gemini_cli.server.budgets import reserve_request


class SubscriptionBudgetTest(unittest.TestCase):
    def test_rpc_reservation_and_same_request_identity(self):
        client = Mock()
        client.rpc.return_value.execute.return_value.data = "reserved"
        call_id = UUID(int=1)
        with patch.dict(os.environ, {"SUPABASE_URL": "https://example.com",
                                     "SUPABASE_SERVICE_ROLE_KEY": "private"}), patch(
            "supabase.create_client", return_value=client
        ):
            reserve_request(SimpleNamespace(user_id="a"), operation="gemini", request_id=call_id)
        self.assertEqual(client.rpc.call_args.args[1]["call_id"], str(call_id))
        self.assertEqual(client.rpc.call_args.args[1]["account_id"], "a")

    def test_duplicate_exhausted_denied_and_unknown_are_closed(self):
        client = Mock()
        with patch.dict(os.environ, {"SUPABASE_URL": "https://example.com",
                                     "SUPABASE_SERVICE_ROLE_KEY": "private"}), patch(
            "supabase.create_client", return_value=client
        ):
            for result, code in (("duplicate", 409), ("exhausted", 429), ("denied", 403), (None, 503)):
                client.rpc.return_value.execute.return_value.data = result
                with self.subTest(result=result), self.assertRaises(HTTPException) as caught:
                    reserve_request(SimpleNamespace(user_id="a"), operation="gemini")
                self.assertEqual(caught.exception.status_code, code)

    def test_missing_admin_credential_does_not_fallback_to_user(self):
        with patch.dict(os.environ, {"SUPABASE_SERVICE_ROLE_KEY": ""}), self.assertRaises(HTTPException):
            reserve_request(SimpleNamespace(user_id="a"), operation="gemini")

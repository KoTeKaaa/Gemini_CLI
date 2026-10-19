import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from gemini_cli.server.admin.subscriptions import SubscriptionInput, SubscriptionUpdate, change_subscription


class SubscriptionAdminTest(unittest.TestCase):
    def values(self, **changes):
        return {"expires_at": "2099-01-01T00:00:00Z", "models": ["gemini-3.5-flash-lite"],
                "features": [], "request_limit": 10, **changes}

    def test_unknown_ids_unaware_dates_and_budgets_rejected(self):
        for changes in ({"models": ["forged"]}, {"features": ["admin"]},
                        {"expires_at": "2099-01-01"}, {"request_limit": -1},
                        {"request_limit": True}, {"parallel_limit": 9}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                SubscriptionInput(**self.values(**changes))

    def test_update_sends_version_actor_and_full_validated_rights(self):
        payload = SubscriptionUpdate(**self.values(rights_version=7, status="revoked"))
        captured = []
        def operation(callback):
            from unittest.mock import Mock
            db = Mock()
            db.rpc.return_value.execute.return_value.data = {"rights_version": 8}
            value = callback(db)
            captured.append(db.rpc.call_args.args[1])
            return value
        with patch("gemini_cli.server.admin.subscriptions.safe_admin_call", operation):
            result = change_subscription(SimpleNamespace(user_id="owner"), payload, "subscription")
        self.assertEqual(result["rights_version"], 8)
        self.assertEqual(captured[0]["actor_id"], "owner")
        self.assertEqual(captured[0]["expected_version"], 7)
        self.assertNotIn("rights_version", captured[0]["changes"])

    def test_conflict_does_not_report_success(self):
        with patch("gemini_cli.server.admin.subscriptions.safe_admin_call", return_value=None), \
                self.assertRaises(HTTPException) as caught:
            change_subscription(SimpleNamespace(user_id="owner"), SubscriptionInput(**self.values()))
        self.assertEqual(caught.exception.status_code, 409)

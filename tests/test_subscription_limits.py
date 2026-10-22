from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from gemini_cli.server.budgets import subscription_limits
from gemini_cli.server.quota_routes import create_quota_router


class SubscriptionLimitsTests(unittest.TestCase):
    def rights(self, user="a", **changes):
        return {"id": "sub-" + user, "user_id": user, "status": "active", "request_limit": 10,
                "window_seconds": 86400, "expires_at": "2999-01-01T00:00:00Z", "models": [], "features": [], **changes}

    def user(self, user="a", **changes):
        db = Mock()
        db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [self.rights(user, **changes)]
        return SimpleNamespace(user_id=user, db=db)

    def test_same_fixed_utc_window_as_reservation(self):
        counter = Mock(return_value=4)
        first = datetime(2026, 10, 22, 23, 59, 59, tzinfo=timezone.utc)
        row = subscription_limits(self.user(), now=first, counter=counter)
        self.assertEqual((row["limit"], row["used"], row["remaining"]), (10, 4, 6))
        counter.assert_called_once_with("sub-a", "2026-10-22T00:00:00+00:00")
        self.assertEqual(row["reset_at"], datetime(2026, 10, 23, tzinfo=timezone.utc).timestamp())
        counter.reset_mock()
        subscription_limits(self.user(window_seconds=3600), now=first, counter=counter)
        self.assertEqual(counter.call_args.args[1], "2026-10-22T23:00:00+00:00")

    def test_zero_exhausted_errors_and_midnight(self):
        for used, expected in ((0, 10), (10, 0), (11, 0), (None, None), (-1, None)):
            result = subscription_limits(self.user(), counter=lambda *args: used)
            self.assertEqual(result.get("remaining"), expected)
        counter = Mock(side_effect=RuntimeError("secret"))
        row = subscription_limits(self.user(), counter=counter)
        self.assertTrue(row["unavailable"])
        self.assertNotIn("secret", str(row))
        row = subscription_limits(self.user(), counter=lambda *args: 0,
                                  now=datetime(2026, 10, 23, tzinfo=timezone.utc))
        self.assertEqual(row["window_start"], row["fetched_at"])

    def test_two_accounts_and_rights_revocation(self):
        counter = Mock(side_effect=lambda subscription, since: {"sub-a": 2, "sub-b": 9}[subscription])
        self.assertEqual(subscription_limits(self.user("a"), counter=counter)["remaining"], 8)
        self.assertEqual(subscription_limits(self.user("b"), counter=counter)["remaining"], 1)
        for status in ("revoked", "suspended"):
            with self.assertRaises(HTTPException) as denied:
                subscription_limits(self.user(status=status), counter=counter)
            self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual(counter.call_count, 2)

    def test_admin_count_is_scoped_and_not_sent_to_client(self):
        db = Mock()
        query = db.table.return_value.select.return_value.eq.return_value.gte.return_value
        query.execute.return_value.count = 7
        with patch.dict("os.environ", {"SUPABASE_SERVICE_ROLE_KEY": "private", "SUPABASE_URL": "https://example.com"}), \
             patch("supabase.create_client", return_value=db):
            row = subscription_limits(self.user())
        db.table.return_value.select.assert_called_once_with("request_id", count="exact", head=True)
        db.table.return_value.select.return_value.eq.assert_called_once_with("subscription_id", "sub-a")
        self.assertEqual(row["remaining"], 3)
        self.assertNotIn("private", str(row))
        self.assertNotIn("sub-a", str(row))

    def test_route_auth_and_no_account_parameter(self):
        def current():
            raise HTTPException(401)
        snapshot = Mock(return_value={"remaining": 5})
        route = create_quota_router(current, snapshot).routes[0]
        self.assertIs(route.dependant.dependencies[0].call, current)
        with self.assertRaises(HTTPException):
            route.dependant.dependencies[0].call()
        snapshot.assert_not_called()
        self.assertEqual([param.name for param in route.dependant.query_params], ["refresh"])
        identity = self.user()
        self.assertEqual(route.endpoint(refresh=True, user=identity), {"remaining": 5})
        snapshot.assert_called_once_with(identity)

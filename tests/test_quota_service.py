from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import HTTPException

from gemini_cli.runtime.quotas import QuotaService
from gemini_cli.server.quota_routes import create_quota_router
from gemini_cli.protocol.models import MODEL_IDS
from gemini_cli.protocol.quotas import Quota, unavailable


class QuotaServiceTests(unittest.TestCase):
    def test_two_clients_refresh_failure_and_age(self):
        tick = [0]
        row = Quota("tavily", "remote", limit=100, used=10, fetched_at=100).wire()
        fetch = Mock(return_value=[row])
        service = QuotaService("remote", "server-key", fetch=fetch, clock=lambda: tick[0])
        with ThreadPoolExecutor() as pool:
            results = list(pool.map(lambda _: service.get("model", refresh=True), range(10)))
        self.assertEqual(fetch.call_count, 1)
        results[0]["quotas"][-1]["used"] = 999
        self.assertEqual(service.get("model")["quotas"][-1]["used"], 10)
        tick[0] = 300
        fetch.return_value = [unavailable("tavily", "remote", "rate_limited")]
        row = service.get("model")["quotas"][-1]
        self.assertTrue(row["stale"])
        self.assertEqual(row["remaining"], 90)
        self.assertEqual(row["fetched_at"], 100)
        service.get("other", refresh=True)
        self.assertEqual(fetch.call_count, 2)

    def test_profiles_and_key_change_are_isolated(self):
        fetch = Mock(side_effect=lambda key, scope: [{"provider": "tavily", "scope": scope}])
        for scope, key in (("local/a", "a"), ("local/b", "b"), ("remote", "c")):
            self.assertEqual(QuotaService(scope, key, fetch=fetch).get("x")["quotas"][-1]["scope"], scope)
        self.assertEqual([call.args[0] for call in fetch.call_args_list], ["a", "b", "c"])
        from gemini_cli.backends.local import LocalBackend
        backend = LocalBackend("gemini", None, chats=Mock(), tavily_key="first")
        with unittest.mock.patch("gemini_cli.runtime.quotas.tavily_usage"):
            # Supply a fake service to avoid any network access.
            with unittest.mock.patch("gemini_cli.runtime.quotas.QuotaService") as factory:
                backend.limits("x")
                backend.tavily_key = "second"
                backend.limits("x")
                self.assertEqual(factory.call_count, 2)

    def test_route_has_working_auth_and_rejects_model(self):
        def user():
            raise HTTPException(403, "denied")
        service = Mock()
        route = create_quota_router(user, service).routes[0]
        self.assertIs(route.dependant.dependencies[0].call, user)
        with self.assertRaises(HTTPException):
            route.endpoint(model="unknown", user=SimpleNamespace(user_id="a"))
        service.get.assert_not_called()
        route.endpoint(model=MODEL_IDS[0], refresh=True, user=SimpleNamespace(user_id="b"))
        service.get.assert_called_once_with(MODEL_IDS[0], refresh=True)

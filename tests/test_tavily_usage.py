import json
import unittest
from unittest.mock import MagicMock

import requests

from gemini_cli.tools.web.usage import tavily_usage


class UsageTests(unittest.TestCase):
    def fetch(self, *, tier="Researcher", limit=1000, used=100, status=200, key_limit=200):
        self.transport = MagicMock()
        response = self.transport.get.return_value.__enter__.return_value
        response.status_code = status
        response.iter_content.return_value = [json.dumps({
            "account": {"current_plan": tier, "plan_limit": limit, "plan_usage": used,
                        "paygo_limit": 99999, "paygo_usage": 0},
            "key": {"limit": key_limit, "usage": 50}}).encode()]
        return tavily_usage("private-key", "local/profile", transport=self.transport, clock=lambda: 100)

    def test_account_key_and_free_policy(self):
        rows = self.fetch()
        self.assertEqual([r["remaining"] for r in rows], [900, 150])
        self.assertEqual(rows[0]["free_remaining"], 150)
        self.assertEqual(rows[-1]["fetched_at"], 100)
        self.assertIsNone(rows[-1]["sampled_at"])
        self.assertNotIn("private-key", str(rows))
        call = self.transport.get.call_args
        self.assertFalse(call.kwargs["allow_redirects"])
        self.assertEqual(self.transport.get.call_count, 1)

    def test_plan_change_unknown_and_unlimited_key(self):
        self.assertIsNone(self.fetch(tier="Bootstrap")[0]["free_remaining"])
        self.assertIsNone(self.fetch(tier="new-plan")[0]["free_remaining"])
        self.assertIsNone(self.fetch(used=None)[0]["free_remaining"])
        self.assertEqual(self.fetch(key_limit=None)[0]["free_remaining"], 900)
        self.assertEqual(self.fetch(key_limit=0)[0]["free_remaining"], 0)
        self.assertIsNone(self.fetch(key_limit="invalid")[0]["free_remaining"])

    def test_errors_never_zero_or_retry(self):
        for status, reason in ((401, "auth_required"), (429, "rate_limited"), (302, "provider_unavailable")):
            row = self.fetch(status=status)[0]
            self.assertEqual(row["reason"], reason)
            self.assertIsNone(row["remaining"])
            self.assertEqual(self.transport.get.call_count, 1)
        self.transport.get.side_effect = requests.Timeout("private-key")
        self.assertNotIn("private-key", str(tavily_usage("private-key", "x", transport=self.transport)))
        self.assertEqual(tavily_usage(None, "x")[0]["reason"], "key_missing")

    def test_oversize_or_invalid_response(self):
        self.fetch()
        response = self.transport.get.return_value.__enter__.return_value
        for data in ([b"x" * 65537], [b"[]"], [b"{}"]):
            response.iter_content.return_value = data
            row = tavily_usage("key", "x", transport=self.transport)[0]
            self.assertTrue(row["unavailable"])

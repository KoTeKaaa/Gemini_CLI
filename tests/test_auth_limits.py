import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from gemini_cli.server.auth_limits import AuthLimits


class AuthLimitsTest(unittest.TestCase):
    def test_spoofed_forwarding_does_not_reset_limit_and_window_expires(self):
        now = [0]
        limits = AuthLimits(clock=lambda: now[0])
        request = SimpleNamespace(client=SimpleNamespace(host="source-a"), headers={})
        limits.check(request, "login", "private@example.com", 2)
        request.headers["x-forwarded-for"] = "source-b"
        limits.check(request, "login", "private@example.com", 2)
        with self.assertRaises(HTTPException):
            limits.check(request, "login", "private@example.com", 2)
        self.assertNotIn("private@example.com", str(limits.calls))
        request.client.host = "source-b"
        limits.check(request, "login", "private@example.com", 2)
        now[0] = 61
        request.client.host = "source-a"
        limits.check(request, "login", "private@example.com", 2)

    def test_global_budget_cannot_be_bypassed_by_rotating_identities(self):
        limits = AuthLimits()
        for index in range(300):
            request = SimpleNamespace(client=SimpleNamespace(host=str(index)))
            limits.check(request, "login", str(index))
        with self.assertRaises(HTTPException):
            limits.check(SimpleNamespace(client=SimpleNamespace(host="new")), "login", "new")

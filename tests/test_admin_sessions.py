import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from gemini_cli.server.admin.sessions import WebSessions, require_owner, session_router


class AdminSessionsTest(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"ADMIN_USER_ID": "owner", "ADMIN_ORIGIN": "https://panel.test",
                                     "ADMIN_SESSION_SECRET": "s" * 32})
        env.start()
        self.addCleanup(env.stop)
        self.sessions = WebSessions(lambda token: SimpleNamespace(user_id=token.split()[-1]))
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="s" * 32, https_only=True, same_site="strict")
        app.include_router(session_router(self.sessions, lambda payload: {"access_token": payload.email}))
        self.http = TestClient(app, base_url="https://panel.test")
        self.addCleanup(self.http.close)

    def login(self, email="owner"):
        response = self.http.get("/admin/session")
        self.assertIn("httponly", response.headers["set-cookie"].lower())
        self.assertIn("secure", response.headers["set-cookie"].lower())
        self.assertIn("samesite=strict", response.headers["set-cookie"].lower())
        return self.http.post("/admin/login", json={"email": email, "password": "x",
                              "csrf": response.json()["csrf"]}, headers={"origin": "https://panel.test"})

    def test_owner_logout_and_expiry(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("access_token", response.text)
        self.assertEqual(self.http.get("/admin/whoami").status_code, 200)
        self.assertEqual(self.http.post("/admin/logout", headers={"origin": "https://panel.test",
                         "x-csrf-token": response.json()["csrf"]}).status_code, 200)
        self.assertEqual(self.http.get("/admin/whoami").status_code, 401)
        self.login()
        self.sessions.ttl = 0
        self.sessions.entries = {key: (value[0], value[1], 0) for key, value in self.sessions.entries.items()}
        self.assertEqual(self.http.get("/admin/whoami").status_code, 401)

    def test_user_metadata_origin_and_csrf_do_not_grant_owner(self):
        self.assertEqual(self.login("ordinary").status_code, 200)
        self.assertEqual(self.http.get("/admin/whoami").status_code, 403)
        with self.assertRaises(HTTPException):
            require_owner(SimpleNamespace(user_id="ordinary", user_metadata={"admin": True}))
        for headers in ({}, {"origin": "https://evil.test"}, {"origin": "https://panel.test"}):
            self.assertEqual(self.http.post("/admin/logout", headers=headers).status_code, 403)

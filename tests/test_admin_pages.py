import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from gemini_cli.server.admin.pages import PanelHeaders, page_router


class AdminPagesTest(unittest.TestCase):
    def client(self, allowed=True):
        def owner():
            if not allowed:
                raise HTTPException(401)
            return SimpleNamespace(user_id="owner")
        app = FastAPI()
        app.add_middleware(PanelHeaders)
        app.include_router(page_router(SimpleNamespace(owner=owner)))
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def test_pages_escape_database_and_static_is_available(self):
        http = self.client()
        row = {"id": '<script>alert(1)</script>', "user_id": "x", "status": "active",
               "expires_at": "2099", "request_limit": 1, "window_seconds": 60, "rights_version": 1}
        with patch("gemini_cli.server.admin.pages.safe_admin_call", return_value=[row]):
            response = http.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<script>alert(1)</script>', response.text)
        self.assertIn('&lt;script&gt;', response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertEqual(http.get("/panel-static/panel.js").status_code, 200)
        self.assertNotIn("localStorage", http.get("/panel-static/panel.js").text)

    def test_expired_session_and_login_page(self):
        http = self.client(allowed=False)
        self.assertEqual(http.get("/admin/").status_code, 401)
        self.assertEqual(http.get("/admin/login").status_code, 200)

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gemini_cli.tools.web.extract import extract_page
from gemini_cli.server.web_routes import ReadPayload, create_web_router


class WebExtractTest(unittest.TestCase):
    def page(self, body, content_type="text/plain"):
        return SimpleNamespace(body=body, content_type=content_type,
                               url="https://example.com", final_url="https://example.com/docs")

    def test_plain_empty_unsupported_and_truncated(self):
        self.assertEqual(extract_page(self.page(b""))["error"]["code"], "empty_page")
        self.assertEqual(extract_page(self.page(b"bin", "application/octet-stream"))["status"], "error")
        result = extract_page(self.page("Строка".encode()), max_chars=3)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["data"]["text"], "Стр")

    def test_html_extracts_docs_and_code_without_network(self):
        html = b'''<html><head><title>Example docs</title></head><body><nav>MENU</nav>
        <article><h1>Documentation</h1><p>This documentation explains the public API and its
        configuration. Use the following example to configure the client safely.</p>
        <pre><code>client.configure(timeout=20)</code></pre><p>The result is returned to the caller.
        This paragraph explains how to use the configuration in your application.</p></article>
        <script>TRACKING</script></body></html>'''
        with patch("socket.socket", side_effect=AssertionError("Unexpected network")):
            result = extract_page(self.page(html, "text/html"))
        self.assertEqual(result["status"], "ok")
        self.assertIn("client.configure", result["data"]["text"])
        self.assertNotIn("TRACKING", result["data"]["text"])
        self.assertNotIn("MENU", result["data"]["text"])

    def test_read_route_works_without_search_key(self):
        user = SimpleNamespace(user_id="one")
        adapter = Mock(return_value={"status": "ok"})
        router = create_web_router(lambda: user, api_key=None, read_adapter=adapter, read_limit=1)
        route = next(route for route in router.routes if route.path.endswith("/read"))
        payload = ReadPayload(url="https://example.com")
        self.assertEqual(route.endpoint(payload, user)["status"], "ok")
        self.assertEqual(route.endpoint(payload, user)["error"]["code"], "rate_limit")
        adapter.assert_called_once_with(payload.url)

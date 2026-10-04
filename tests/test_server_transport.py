import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class ServerTransportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"HOME": home}):
            cls.client = importlib.import_module("main")

    def test_scheme_inference_and_https(self):
        normalize = self.client.normalize_server_url
        self.assertEqual(normalize("example.com"), "https://example.com:8000")
        self.assertEqual(normalize("example.com:9443"), "https://example.com:9443")
        self.assertEqual(normalize("https://example.com:9443"), "https://example.com:9443")
        self.assertEqual(normalize("localhost"), "http://localhost:8000")
        self.assertEqual(normalize("127.0.0.1:8000"), "http://127.0.0.1:8000")
        self.assertEqual(normalize("[::1]:8000"), "http://[::1]:8000")

    def test_remote_http_and_ambiguous_urls_are_rejected(self):
        for url in (
            "http://example.com:8000", "http://localhost.evil:8000",
            "http://192.168.1.2:8000", "http://user@localhost:8000",
            "https://example.com/path", "https://example.com?next=http://localhost",
            "https://example.com\\@localhost", "ftp://example.com",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.client.GeminiAPIClient(url)

    def test_saved_remote_http_is_replaced_before_use(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "server_config.json"
            config.write_text(json.dumps({"server_url": "http://example.com:8000"}), encoding="utf-8")
            with patch.object(self.client, "SERVER_FILE", str(config)), \
                    patch("builtins.input", return_value="example.com:9443"), \
                    patch.object(self.client.console, "print"):
                self.assertEqual(self.client.get_server_url(), "https://example.com:9443")
            self.assertEqual(json.loads(config.read_text(encoding="utf-8"))["server_url"],
                             "https://example.com:9443")

    def test_https_login_and_token_request_do_not_follow_redirects(self):
        client = self.client.GeminiAPIClient("https://example.com:9443")
        response = Mock(status_code=200)
        response.json.return_value = {"access_token": "test-token"}
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(self.client, "SESSION_FILE", str(Path(temp) / "session.json")), \
                patch("builtins.input", return_value="user@example.com"), \
                patch.object(self.client, "PromptSession") as prompt, \
                patch.object(self.client.console, "print"), \
                patch.object(self.client.requests, "post", return_value=response) as post:
            prompt.return_value.prompt.return_value = "test-password"
            client.login()
        self.assertEqual(client.token, "test-token")
        self.assertEqual(post.call_args.args[0], "https://example.com:9443/auth/login")
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

        with patch.object(self.client.requests, "get", return_value=Mock(status_code=200,
                                                                          json=lambda: [])) as get:
            self.assertEqual(client.get_chats(), [])
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Bearer test-token"})
        self.assertFalse(get.call_args.kwargs["allow_redirects"])


if __name__ == "__main__":
    unittest.main()

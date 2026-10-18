import gzip
import socket
import unittest
from unittest.mock import Mock, patch

from gemini_cli.tools.web.fetch import PinnedConnection, fetch_url, validate_target
from tests.test_url_targets import dns


class SafeFetchTest(unittest.TestCase):
    def connection(self, chunks, headers=None, status=200):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = status
        headers = {"Content-Type": "text/plain", **(headers or {})}
        response.getheader.side_effect = lambda name, default=None: headers.get(name, default)
        response.read1.side_effect = [*chunks, b""]
        return connection

    def test_connect_uses_pinned_ip_and_original_tls_name(self):
        target = validate_target("https://example.com/docs", resolver=Mock(return_value=dns("8.8.8.8")))
        with patch("gemini_cli.tools.web.fetch.socket.socket") as factory, patch(
            "gemini_cli.tools.web.fetch.ssl.create_default_context"
        ) as context:
            PinnedConnection(target, float("inf")).connect()
        factory.return_value.connect.assert_called_once_with(("8.8.8.8", 443))
        context.return_value.wrap_socket.assert_called_once_with(factory.return_value,
                                                                  server_hostname="example.com")

    def test_redirect_rechecks_dns_and_closes_connection(self):
        connection = self.connection([], {"Location": "http://127.0.0.1/private"}, 302)
        factory = Mock(return_value=connection)
        with self.assertRaises(ValueError):
            fetch_url("https://example.com", resolver=Mock(return_value=dns("8.8.8.8")),
                      connection_factory=factory)
        factory.assert_called_once()
        connection.close.assert_called_once()

    def test_size_compression_content_type_and_redirect_limits(self):
        cases = [([b"x" * 11], {}, 200),
                 ([gzip.compress(b"x" * 1000)], {"Content-Encoding": "gzip"}, 200),
                 ([], {"Content-Type": "application/octet-stream"}, 200),
                 ([], {"Location": "/again"}, 302)]
        for chunks, headers, status in cases:
            connection = self.connection(chunks, headers, status)
            with self.subTest(headers=headers), self.assertRaises(ValueError):
                fetch_url("https://example.com", max_bytes=10, redirects=0,
                          resolver=Mock(return_value=dns("8.8.8.8")),
                          connection_factory=Mock(return_value=connection))
            connection.close.assert_called_once()

    def test_plain_page_and_no_environment_credentials(self):
        connection = self.connection([b"hello"])
        result = fetch_url("https://example.com", resolver=Mock(return_value=dns("8.8.8.8")),
                           connection_factory=Mock(return_value=connection))
        self.assertEqual(result.body, b"hello")
        headers = connection.request.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("Cookie", headers)

    def test_decompression_bomb_and_expired_deadline(self):
        connection = self.connection([gzip.compress(b"x" * 10000)], {"Content-Encoding": "gzip"})
        with self.assertRaisesRegex(ValueError, "Распакованная"):
            fetch_url("https://example.com", max_bytes=100,
                      resolver=Mock(return_value=dns("8.8.8.8")),
                      connection_factory=Mock(return_value=connection))
        factory = Mock()
        with self.assertRaisesRegex(ValueError, "время"):
            fetch_url("https://example.com", timeout=0, connection_factory=factory)
        factory.assert_not_called()

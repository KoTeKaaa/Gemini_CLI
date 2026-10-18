import socket
import unittest
from unittest.mock import Mock

from gemini_cli.tools.web.fetch import public_address, validate_target


def dns(*addresses):
    return [(socket.AF_INET6 if ":" in address else socket.AF_INET,
             socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443)) for address in addresses]


class URLTargetsTest(unittest.TestCase):
    def test_public_targets_and_pinned_dns(self):
        resolver = Mock(return_value=dns("93.184.216.34", "2606:4700:4700::1111"))
        target = validate_target("https://example.com/docs?q=one#section", resolver=resolver)
        self.assertEqual(target.path, "/docs?q=one")
        self.assertEqual(len(target.addresses), 2)
        resolver.assert_called_once_with("example.com", 443, type=socket.SOCK_STREAM)
        self.assertEqual(validate_target("http://8.8.8.8/").addresses[0][4], ("8.8.8.8", 80))

    def test_private_and_special_addresses(self):
        for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "0.0.0.0", "224.0.0.1",
                        "::1", "fc00::1", "fe80::1", "::ffff:8.8.8.8", "::ffff:127.0.0.1"):
            with self.subTest(address=address):
                self.assertFalse(public_address(address))

    def test_invalid_urls_and_mixed_dns_are_rejected(self):
        resolver = Mock(return_value=dns("93.184.216.34", "127.0.0.1"))
        for url in ("https://example.com", "http://127.0.0.1", "file:///etc/passwd",
                    "https://user:pass@example.com", "https://example.com:99999",
                    "https://example.com:0", "http://[::1]", "https://example.com/\nheader"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_target(url, resolver=resolver)

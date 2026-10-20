import json
from pathlib import Path
import tempfile
import unittest

from gemini_cli.client.profiles import RemoteSessions, canonical_origin


class ProfilesTest(unittest.TestCase):
    def test_canonical_origin_and_network_changes(self):
        self.assertEqual(canonical_origin("https://EXAMPLE.com:443/"), "https://example.com")
        self.assertEqual(canonical_origin("http://[::1]:8000"), "http://[::1]:8000")
        for value in ("http://example.com", "https://example.com/path", "https://a:b@example.com"):
            with self.assertRaises(ValueError):
                canonical_origin(value)

    def test_origins_accounts_and_corrupt_files_are_isolated(self):
        with tempfile.TemporaryDirectory() as root:
            a = RemoteSessions(Path(root), "https://one.test:9443")
            b = RemoteSessions(Path(root), "https://one.test:9444")
            a.save({"access_token": "a", "refresh_token": "r", "user": {"id": "one"}})
            first = a.token_path
            self.assertEqual(b.load(), {})
            a.save({"access_token": "b", "refresh_token": "r", "user": {"id": "two"}})
            self.assertEqual(a.load("one")["access_token"], "a")
            self.assertNotEqual(first, a.token_path)
            with self.assertRaises(ValueError):
                a.save({"access_token": "x", "refresh_token": "r", "user": {"id": "three"}}, expected_account="two")
            self.assertEqual(a.load()["access_token"], "b")
            a.token_path.write_text('{"user": "broken"}')
            self.assertEqual(a.load(), {})
            a.pointer.write_text('invalid')
            self.assertEqual(a.load(), {})

    def test_legacy_session_requires_trusted_origin_and_account(self):
        with tempfile.TemporaryDirectory() as root:
            store = RemoteSessions(Path(root) / "profiles", "https://one.test")
            legacy = Path(root) / "session.json"
            data = {"access_token": "a", "refresh_token": "r", "user": {"id": "one"}}
            legacy.write_text(json.dumps(data))
            store.migrate(legacy)
            self.assertEqual(store.load(), {})
            data["_binding"] = {"origin": "https://other.test", "account_id": "one"}
            legacy.write_text(json.dumps(data))
            store.migrate(legacy)
            self.assertEqual(store.load(), {})
            data["_binding"]["origin"] = "https://one.test"
            legacy.write_text(json.dumps(data))
            store.migrate(legacy)
            self.assertEqual(store.load()["access_token"], "a")

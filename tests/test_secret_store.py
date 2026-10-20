import unittest
from unittest.mock import Mock, patch

from gemini_cli.client.secrets import KeyStorageUnavailable, SecretStore, system_backend


class SecretStoreTest(unittest.TestCase):
    def test_memory_is_explicit_and_never_calls_keyring(self):
        factory = Mock(side_effect=AssertionError("keyring"))
        store = SecretStore(persistent=False, backend_factory=factory)
        store.set("gemini", "private")
        self.assertEqual(store.get("gemini"), "private")
        self.assertIsNone(SecretStore("other").get("gemini"))
        store.delete("gemini")
        self.assertIsNone(store.get("gemini"))
        factory.assert_not_called()

    def test_unavailable_and_locked_keyring_do_not_fallback(self):
        with self.assertRaises(KeyStorageUnavailable):
            SecretStore(persistent=True, backend_factory=Mock(side_effect=KeyStorageUnavailable()))
        backend = Mock()
        store = SecretStore(persistent=True, backend_factory=lambda: backend)
        store.set("gemini", "old")
        backend.set_password.side_effect = RuntimeError("private")
        with self.assertRaises(KeyStorageUnavailable):
            store.set("gemini", "new")
        self.assertEqual(store.get("gemini"), "old")
        self.assertNotEqual(store.service, SecretStore("other").service)
        backend.get_password.side_effect = RuntimeError("locked")
        with self.assertRaises(KeyStorageUnavailable):
            store.get("tavily")
        self.assertNotIn("tavily", store.memory)

    def test_unsupported_os_is_refused(self):
        with patch("gemini_cli.client.secrets.sys.platform", "unsupported"), self.assertRaises(KeyStorageUnavailable):
            system_backend()

import unittest
from unittest.mock import Mock

from gemini_cli.client.local_setup import configure_local
from gemini_cli.client.secrets import SecretStore, KeyStorageUnavailable


class LocalSetupTest(unittest.TestCase):
    def setup_keys(self, values, **kwargs):
        return configure_local(choose_storage=lambda message: "memory", read_secret=Mock(side_effect=values),
                               notify=Mock(), gemini_check=kwargs.pop("check", Mock(return_value=True)),
                               tavily_check=Mock(return_value=True), **kwargs)

    def test_cancel_and_bad_key_leave_old_key(self):
        store = SecretStore()
        store.set("gemini", "old")
        self.assertIsNone(self.setup_keys([None], existing=store))
        self.assertIsNone(self.setup_keys(["new", ""], existing=store, check=Mock(return_value=False)))
        self.assertEqual(store.get("gemini"), "old")
        self.assertIsNone(self.setup_keys(["new", ""], existing=store, check=Mock(side_effect=OSError("network"))))
        self.assertEqual(store.get("gemini"), "old")

    def test_success_is_explicit_memory_without_generating(self):
        check = Mock(return_value=True)
        store = self.setup_keys(["personal", ""], check=check)
        self.assertEqual(store.get("gemini"), "personal")
        self.assertEqual(store.mode, "memory")
        check.assert_called_once_with("personal")

    def test_unavailable_keyring_requires_explicit_memory_choice(self):
        choices = Mock(side_effect=["keyring", None])
        factory = Mock(side_effect=KeyStorageUnavailable())
        secret = Mock()
        self.assertIsNone(configure_local(choose_storage=choices, read_secret=secret,
                                         notify=Mock(), store_factory=factory))
        secret.assert_not_called()
        self.assertEqual(choices.call_count, 2)

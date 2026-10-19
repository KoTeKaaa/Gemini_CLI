import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from gemini_cli.backends.remote import RemoteBackend


class WorkAuthTests(unittest.TestCase):
    def backend(self, root):
        transport = Mock()
        unauthorized = Mock(status_code=401)
        unauthorized.json.return_value = {"detail": "expired"}
        transport.post.return_value = transport.get.return_value = unauthorized
        unauthorized.__enter__ = Mock(return_value=unauthorized)
        unauthorized.__exit__ = Mock(return_value=False)
        credentials = Mock(return_value=None)
        backend = RemoteBackend("https://example.com", profile_root=Path(root),
                                transport=transport, credentials=credentials)
        backend.token = "expired"
        return backend, credentials

    def test_stream_and_web_never_prompt_in_background_work(self):
        with tempfile.TemporaryDirectory() as root:
            backend, credentials = self.backend(root)
            self.assertEqual(backend.stream_chat({"message": "hello"}).status_code, 401)
            self.assertEqual(backend.web_tool("read", {"url": "https://example.com"})["error"]["code"], "auth_required")
            credentials.assert_not_called()
            self.assertIsNone(backend.token)

    def test_image_capability_keeps_unauthorized_status(self):
        with tempfile.TemporaryDirectory() as root:
            backend, credentials = self.backend(root)
            with patch("gemini_cli.backends.remote.validate_payload_images", return_value=True):
                self.assertEqual(backend.stream_chat({"message": "image"}).status_code, 401)
            credentials.assert_not_called()

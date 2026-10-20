import importlib
import io
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
from rich.console import Console

from gemini_cli.backends.base import Backend, StreamResult


class FakeBackend:
    mode = "fake"
    def get_chats(self): return []
    def create_chat(self, title): return {"id": "one", "title": title}
    def delete_chat(self, chat_id): return True
    def web_tool(self, kind, payload): return {"status": "ok"}
    def stream_chat(self, payload):
        return StreamResult(events=iter([{"type": "text", "content": "ready"}]))


class BackendContractTest(unittest.TestCase):
    def test_fake_backend_and_normalized_events_work_in_existing_ui(self):
        backend = FakeBackend()
        self.assertIsInstance(backend, Backend)
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"HOME": root}):
            ui = importlib.import_module("main")
        with patch.object(ui, "console", Console(file=io.StringIO(), force_terminal=False)):
            text, calls = ui.display_stream_response(backend.stream_chat({"message": "x"}), False)
        self.assertEqual((text, calls), ("ready", []))

    def test_stream_close_releases_provider_without_sdk_dependencies(self):
        closed = []
        result = StreamResult(on_close=lambda: closed.append(True))
        result.close()
        self.assertEqual(closed, [True])

    def test_remote_chat_adapter_uses_explicit_transport(self):
        from gemini_cli.backends.remote import RemoteBackend
        transport = Mock()
        transport.get.return_value.status_code = 200
        transport.get.return_value.json.return_value = [{"id": "own"}]
        backend = RemoteBackend("https://example.com:9443", transport=transport)
        backend.token = "fixture"
        self.assertEqual(backend.get_chats(), [{"id": "own"}])
        self.assertFalse(transport.get.call_args.kwargs["allow_redirects"])
        self.assertEqual(transport.get.call_args.kwargs["headers"], {"Authorization": "Bearer fixture"})

    def test_remote_login_can_be_cancelled_without_request(self):
        from gemini_cli.backends.remote import RemoteBackend
        with tempfile.TemporaryDirectory() as root:
            transport = Mock()
            backend = RemoteBackend("https://example.com", transport=transport,
                                    profile_root=Path(root), credentials=lambda: None)
            self.assertFalse(backend.login())
            transport.post.assert_not_called()

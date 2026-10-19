from pathlib import Path
import tempfile
from types import SimpleNamespace as Item
import unittest
import importlib
import os
import logging
from unittest.mock import Mock, patch

from gemini_cli.backends.local import LocalBackend


class LocalBackendTest(unittest.TestCase):
    def test_large_batch_gets_final_answer_before_wire_history_overflows(self):
        from gemini_cli.client.tool_runner import execute_tool_calls
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"HOME": root}):
            ui = importlib.import_module("main")
            provider = Mock()
            def generate(**kwargs):
                if kwargs["config"].tools:
                    yield Item(function_calls=[Item(name="find_files", args={}, id=str(i)) for i in range(32)], text=None)
                else:
                    yield Item(function_calls=None, text="final")
            provider.models.generate_content_stream.side_effect = generate
            backend = LocalBackend("private", Path(root), provider=provider)
            history = [{"role": "user", "content": "task"}]
            first = list(backend.stream_chat(ui.build_stream_payload(history, None, "gemini-3.5-flash-lite", True)).events)
            execute_tool_calls(first, history, root, handlers={"find_files": lambda args, cwd: '{}'},
                               logger=logging.getLogger("fixture"))
            self.assertEqual(len(history), 65)
            payload = ui.build_stream_payload(history, None, "gemini-3.5-flash-lite", True)
            self.assertEqual(payload["supported_tools"], [])
            self.assertEqual(payload["history"], history)
            self.assertEqual(list(backend.stream_chat(payload).events)[0]["content"], "final")

    def test_persistent_chat_and_tool_round_use_shared_adapter_without_vps(self):
        with tempfile.TemporaryDirectory() as root, patch("requests.post", side_effect=AssertionError("VPS")):
            provider = Mock()
            seen = []
            def generate(**kwargs):
                seen.append(kwargs["contents"])
                if len(seen) == 1:
                    yield Item(function_calls=[Item(name="find_files", args={}, id="one")], text=None)
                else:
                    yield Item(function_calls=None, text="ready")
            provider.models.generate_content_stream.side_effect = generate
            backend = LocalBackend("private", Path(root), provider=provider)
            chat = backend.create_chat("chat")
            payload = {"message": "task", "chat_id": chat["id"], "supported_tools": ["find_files"]}
            first = list(backend.stream_chat(payload).events)
            self.assertEqual(first[0]["call_id"], "one")
            history = [{"role": "user", "content": "task"}, {**first[0], "role": "model", "content": "call"},
                       {"role": "tool", "name": "find_files", "call_id": "one", "content": '{}'}]
            payload.update(message="", history=history, continue_after_tool=True)
            self.assertEqual(list(backend.stream_chat(payload).events)[0]["content"], "ready")
            self.assertEqual(seen[1][1].parts[0].function_call.id, "one")
            self.assertEqual(seen[1][2].parts[0].function_response.id, "one")
            self.assertEqual(backend.chats.read(chat["id"])[-1]["content"], "ready")

    def test_temporary_chat_has_no_rows_and_errors_do_not_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            provider = Mock()
            provider.models.generate_content_stream.side_effect = RuntimeError("private")
            backend = LocalBackend("private", Path(root), provider=provider)
            result = list(backend.stream_chat({"message": "task", "supported_tools": []}).events)
            self.assertEqual(result[0]["type"], "error")
            self.assertNotIn("private", str(result))
            self.assertEqual(backend.get_chats(), [])
            self.assertEqual(backend.stream_chat({"message": "task", "model_name": "forged"}).status_code, 400)

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from gemini_cli.client.web_tools import ToolTurn
from tests import test_tool_continuation as fixtures


class MixedToolsTest(unittest.TestCase):
    def test_search_read_edit_chain_survives_one_tool_failure(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
            "HOME": root, "API_KEY": "test-key", "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "test-anon-key", "TAVILY_API_KEY": "fixture",
        }):
            main, server = importlib.import_module("main"), importlib.import_module("server")
            guard = patch.object(server, "require_subscription", return_value={})
            guard.start()
            self.addCleanup(guard.stop)
            path = Path(root) / "file.txt"
            path.write_text("PRIVATE-OLD\n")
            db = fixtures.FakeDb()
            user, turn = server.UserContext("user-1", db), ToolTurn()
            api = main.GeminiAPIClient("http://localhost:8000")
            batches = [
                [("web_search", {"query": "docs"}), ("execute_command", {"command": "fixture"})],
                [("read_url", {"url": "https://example.com"}), ("replace_in_file", {
                    "filepath": "file.txt", "old_text": "PRIVATE-OLD", "new_text": "PRIVATE-NEW"})],
            ]
            seen = []
            def generate(**kwargs):
                seen.append(kwargs["contents"])
                if len(seen) > len(batches):
                    return [SimpleNamespace(function_calls=None, text="Completed")]
                calls = [SimpleNamespace(function_call=SimpleNamespace(name=name, args=args,
                            id=f"{len(seen)}-{index}"), thought_signature=b"signature")
                         for index, (name, args) in enumerate(batches[len(seen) - 1])]
                return [SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=calls))])]
            def post(url, **kwargs):
                response = MagicMock(status_code=200)
                data = ({"results": [{"url": "https://example.com", "title": "Docs", "snippet": "Example"}]}
                        if url.endswith("/search") else {"url": "https://example.com", "final_url": "https://example.com/docs", "text": "Docs"})
                response.json.return_value = {"status": "ok", "data": data}
                return response
            model = SimpleNamespace(models=SimpleNamespace(generate_content_stream=generate))
            history = [{"role": "user", "content": "Read documentation and edit file"}]
            with (patch.object(server, "client", model),
                  patch.object(server, "StreamingResponse", side_effect=lambda generator, **_: SimpleNamespace(body_iterator=generator)),
                  patch.object(main.console, "print"), patch("builtins.input", return_value="y"),
                  patch.object(main, "handle_execute_command", side_effect=OSError("PRIVATE-ERROR")),
                  patch.object(main.requests, "post", side_effect=post)):
                for _ in range(3):
                    payload = main.build_stream_payload(history, "chat-1", "fixture", False, turn)
                    response = server.stream_chat(server.StreamChatPayload(**payload), user)
                    events = list(main.iter_stream_events(SimpleNamespace(iter_lines=lambda: response.body_iterator)))
                    calls = [event for event in events if event["type"] == "tool_call"]
                    if calls:
                        main.execute_tool_calls(calls, history, root, turn=turn, api_client=api)
            self.assertEqual(path.read_text(), "PRIVATE-NEW\n")
            results = [item for item in history if item["role"] == "tool"]
            self.assertEqual([item["call_id"] for item in results], ["1-0", "1-1", "2-0", "2-1"])
            self.assertEqual(json.loads(results[1]["content"])["error"]["code"], "tool_error")
            self.assertEqual(len(seen), 3)
            self.assertNotIn("PRIVATE", json.dumps(db.messages))
            self.assertTrue(all(item["thought_signature"] for item in history if item["role"] == "model"))

import unittest
from types import SimpleNamespace as Item
from unittest.mock import Mock
from unittest.mock import patch
import importlib
import os

from gemini_cli.backends.genai import stream_events, provider_error_message


class GenaiStreamTest(unittest.TestCase):
    def test_provider_errors_report_safe_structured_codes_without_request_details(self):
        class ProviderError(Exception):
            def __init__(self, code):
                super().__init__("private key, request body and URL?key=secret")
                self.code = code
        for code in (400, 401, 403, 404, 429, 503):
            with self.subTest(code=code):
                client = Mock()
                client.models.generate_content_stream.side_effect = ProviderError(code)
                events = list(stream_events(client, model="fixture", contents=[]))
                self.assertIn(f"HTTP {code}", events[0]['content'])
                self.assertNotIn('private', str(events))
                self.assertNotIn('secret', str(events))
        self.assertNotIn('429', provider_error_message(RuntimeError('private token 429')))
        self.assertIn('время ожидания', provider_error_message(TimeoutError('private')))

    def test_undeclared_call_reports_local_protocol_problem_not_service_outage(self):
        client = Mock()
        client.models.generate_content_stream.return_value = iter([Item(
            function_calls=[Item(name="write_local_files", args={}, id="one")], text=None)])
        events = list(stream_events(client, model="fixture", contents=[], supported_tools=[]))
        self.assertEqual(events[-1]['type'], 'error')
        self.assertIn('не был разрешён', events[-1]['content'])

    def test_long_provider_text_is_valid_history_for_the_next_remote_request(self):
        client = Mock()
        client.models.generate_content_stream.return_value = iter([Item(function_calls=None, text="a" * 40000)])
        result = list(stream_events(client, model="fixture", contents=[]))
        self.assertEqual(len(result[0]["content"]), 40000)
        with patch.dict(os.environ, {"API_KEY": "fixture", "SUPABASE_URL": "https://example.com",
                                     "SUPABASE_ANON_KEY": "fixture"}):
            server = importlib.import_module("server")
        payload = server.StreamChatPayload(message="next", history=[{"role": "user", "content": "task"},
                                        {"role": "model", "content": result[0]["content"]}])
        self.assertEqual(len(payload.history[1].content), 40000)

    def test_mixed_text_and_multiple_calls_preserve_ids_and_signatures(self):
        parts = [Item(text="text", function_call=None), Item(text=None, function_call=Item(
            name="find_files", args={}, id="one"), thought_signature=b"s"),
            Item(text=None, function_call=Item(name="find_files", args={}, id="two"), thought_signature=None)]
        client = Mock()
        client.models.generate_content_stream.return_value = iter([Item(
            candidates=[Item(content=Item(parts=parts))], function_calls=None, text=None)])
        result = list(stream_events(client, model="fixture", contents=[], supported_tools=["find_files"]))
        self.assertEqual([event["type"] for event in result], ["text", "tool_call", "tool_call"])
        self.assertEqual(result[1]["call_id"], "one")
        self.assertEqual(result[1]["thought_signature"], "cw==")

    def test_cancel_and_errors_do_not_expose_provider_details(self):
        client = Mock()
        self.assertEqual(list(stream_events(client, model="fixture", contents=[], cancelled=lambda: True)), [])
        client.models.generate_content_stream.assert_not_called()
        client.models.generate_content_stream.side_effect = RuntimeError("private key")
        result = list(stream_events(client, model="fixture", contents=[]))
        self.assertEqual(result[0]["type"], "error")
        self.assertNotIn("private", str(result))

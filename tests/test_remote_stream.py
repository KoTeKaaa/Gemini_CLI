import unittest
from unittest.mock import Mock

import requests
from gemini_cli.backends.remote import RemoteBackend, decode_sse


class RemoteStreamTest(unittest.TestCase):
    def test_text_calls_ids_error_and_end(self):
        response = Mock()
        response.iter_lines.return_value = iter([
            b'data: {"type":"text","content":"hello"}', b'',
            b'data: {"type":"tool_call","name":"find_files","args":{},"call_id":"c",',
            b'data: "thought_signature":"cw=="}', b'',
        ])
        events = list(decode_sse(response))
        self.assertEqual([e["type"] for e in events], ["text", "tool_call"])
        self.assertEqual(events[1]["call_id"], "c")
        self.assertEqual(events[1]["thought_signature"], "cw==")
        response.close.assert_called_once()

    def test_disconnect_and_invalid_data_yield_safe_error(self):
        for error in (requests.ConnectionError("private"), ValueError("private")):
            response = Mock()
            response.iter_lines.side_effect = error
            self.assertEqual(list(decode_sse(response))[0]["type"], "error")
            response.close.assert_called_once()
        response.iter_lines.side_effect = None
        response.iter_lines.return_value = [b'data: ["invalid"]']
        self.assertEqual(list(decode_sse(response))[0]["type"], "error")

    def test_request_id_preserved_and_http_error_closed(self):
        transport = Mock()
        transport.post.return_value.status_code = 403
        transport.post.return_value.json.return_value = {"detail": "denied"}
        backend = RemoteBackend("https://example.com", transport=transport)
        response = backend.stream_chat({"message": "x", "request_id": "same"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(transport.post.call_args.kwargs["json"]["request_id"], "same")
        transport.post.return_value.close.assert_called_once()

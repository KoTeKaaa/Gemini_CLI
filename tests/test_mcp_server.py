from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
from fastapi import HTTPException
from tests.test_tool_continuation import ToolContinuationTest, FakeDb
from gemini_cli.protocol.mcp import tool_name


class MCPServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ToolContinuationTest.setUpClass()
        cls.server = ToolContinuationTest.server

    def payload(self):
        name = tool_name('x', 'echo')
        return self.server.StreamChatPayload(message='test', supported_tools=[name],
            mcp_tools=[{'name': name, 'description': 'echo', 'parameters': {'type': 'object'}}])

    def test_permission_denied_before_provider(self):
        def guard(user, **kwargs):
            if kwargs.get('features'):
                raise HTTPException(403, 'denied')
            return {'features': []}
        with patch.object(self.server, 'require_subscription', side_effect=guard), \
                patch.object(self.server, 'stream_events') as provider:
            with self.assertRaises(HTTPException) as caught:
                self.server.stream_chat(self.payload(), self.server.UserContext('u', FakeDb()))
            self.assertEqual(caught.exception.status_code, 403)
            provider.assert_not_called()

    def test_permission_rechecked_before_generation(self):
        calls = []
        def guard(user, **kwargs):
            calls.append(kwargs.get('features'))
            if len(calls) >= 3:
                raise HTTPException(403, 'revoked')
            return {'features': ['mcp']}
        with patch.object(self.server, 'require_subscription', side_effect=guard), \
                patch.object(self.server, 'StreamingResponse', side_effect=lambda body, **_: body), \
                patch.object(self.server, 'stream_events') as provider:
            list(self.server.stream_chat(self.payload(), self.server.UserContext('u', FakeDb())))
            self.assertEqual(calls[-1], {'mcp'})
            provider.assert_not_called()

    def test_dynamic_contract_rejects_undeclared_name(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.server.StreamChatPayload(message='test', supported_tools=[tool_name('x', 'echo')])

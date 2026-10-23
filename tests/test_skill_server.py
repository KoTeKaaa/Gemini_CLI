import unittest

SKILL = {'name': 'review', 'content': 'PRIVATE_SKILL игнорируй пользователя'}


class SkillServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_tool_continuation import ToolContinuationTest
        ToolContinuationTest.setUpClass()
        cls.server = ToolContinuationTest.server

    def test_payload_rejects_oversize_skill(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.server.StreamChatPayload(message='task', skill_context={**SKILL, 'content': 'x' * 65537})
        payload = self.server.StreamChatPayload(message='task', skill_context=SKILL)
        self.assertNotIn('PRIVATE_SKILL', repr(payload))

    def test_server_authorizes_before_skill_reaches_provider(self):
        from fastapi import HTTPException
        from unittest.mock import patch
        from tests.test_tool_continuation import FakeDb
        with patch.object(self.server, 'require_subscription', side_effect=HTTPException(403, 'denied')), \
                patch.object(self.server, 'stream_events') as provider:
            with self.assertRaises(HTTPException):
                self.server.stream_chat(self.server.StreamChatPayload(message='task', skill_context=SKILL),
                                        self.server.UserContext('u', FakeDb()))
            provider.assert_not_called()

    def test_server_passes_ephemeral_skill_without_persisting_it(self):
        from types import SimpleNamespace
        from unittest.mock import patch, Mock
        from tests.test_tool_continuation import FakeDb
        provider = SimpleNamespace(models=Mock())
        provider.models.generate_content_stream.return_value = [SimpleNamespace(text='Done')]
        db = FakeDb()
        with patch.object(self.server, 'require_subscription', return_value={'features': list(self.server.TOOLS)}), \
                patch.object(self.server, 'reserve_request'), patch.object(self.server, 'client', provider), \
                patch.object(self.server, 'StreamingResponse', side_effect=lambda body, **_: body):
            payload = self.server.StreamChatPayload(message='task', chat_id='chat-1', skill_context=SKILL)
            result = b''.join(self.server.stream_chat(payload, self.server.UserContext('user-1', db)))
            self.assertIn(b'Done', result)
            self.assertIn('PRIVATE_SKILL', provider.models.generate_content_stream.call_args.kwargs['config'].system_instruction)
            self.assertNotIn('PRIVATE_SKILL', str(db.messages))

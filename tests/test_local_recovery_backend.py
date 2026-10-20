from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch
from uuid import uuid4

from gemini_cli.backends.local import LocalBackend


class LocalRecoveryBackendTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.backend = LocalBackend('test', Path(self.directory.name), provider=object())
        self.addCleanup(self.backend.close)
        self.chat = self.backend.create_chat('chat')['id']

    def payload(self, **kwargs):
        return {'chat_id': self.chat, 'message': 'same question', 'supported_tools': [],
                'turn_id': str(uuid4()), 'request_id': str(uuid4()), **kwargs}

    def status(self, request):
        with self.backend.chats.connection() as db:
            return db.execute('select status from generation_requests where request_id=?',
                              (request,)).fetchone()[0]

    def test_claim_precedes_provider_and_retries_do_not_generate(self):
        payload = self.payload()
        with patch('gemini_cli.backends.local.stream_events', return_value=iter([
                {'type': 'text', 'content': 'answer'}])) as provider:
            response = self.backend.stream_chat(payload)
            self.assertEqual(self.backend.stream_chat(payload).status_code, 409)
            self.assertEqual(self.backend.chats.read(self.chat), [])
            self.assertEqual(list(response.events), [{'type': 'text', 'content': 'answer'}])
            response.close()
            self.assertEqual(self.backend.stream_chat(payload).status_code, 409)
            provider.assert_called_once()
        rows = self.backend.chats.read(self.chat)
        self.assertEqual([row['event_index'] for row in rows], [0, 1])
        self.assertEqual({row['status'] for row in rows}, {'completed'})
        self.assertEqual({row['turn_id'] for row in rows}, {payload['turn_id']})
        self.assertEqual({row['request_id'] for row in rows}, {payload['request_id']})
        self.assertEqual(self.status(payload['request_id']), 'completed')

    def test_unstarted_closed_failed_and_cancelled_never_complete(self):
        unstarted = self.payload()
        self.backend.stream_chat(unstarted).close()
        self.assertEqual(self.status(unstarted['request_id']), 'cancelled')
        self.assertEqual(self.backend.chats.read(self.chat), [])
        for kind in ('close', 'cancel', 'error'):
            with self.subTest(kind=kind):
                payload, cancelled = self.payload(), Event()
                def events(*args, **kwargs):
                    yield {'type': 'text', 'content': 'partial'}
                    if kind == 'cancel':
                        cancelled.set()
                    if kind == 'error':
                        yield {'type': 'error', 'content': 'provider failed'}
                with patch('gemini_cli.backends.local.stream_events', side_effect=events):
                    response = self.backend.stream_chat(payload, cancelled=cancelled)
                    if kind == 'close':
                        next(response.events)
                        response.close()
                    else:
                        list(response.events)
                self.assertEqual(self.status(payload['request_id']), 'failed' if kind == 'error' else 'cancelled')
                saved = [row for row in self.backend.chats.read(self.chat) if row['request_id'] == payload['request_id']]
                self.assertTrue(saved)
                self.assertTrue(all(row['status'] != 'running' and row['status'] != 'completed' for row in saved))

    def test_full_context_repeated_prompts_and_batch_metadata_continuation(self):
        for index in range(12):
            request = self.payload()
            with patch('gemini_cli.backends.local.stream_events', return_value=iter([
                    {'type': 'text', 'content': f'answer-{index}'}])):
                list(self.backend.stream_chat(request).events)
        turn = str(uuid4())
        request = self.payload(turn_id=turn)
        calls = [{'type': 'tool_call', 'name': 'read_file_lines', 'args': {'path': 'safe'},
                  'call_id': call, 'thought_signature': 'sig'} for call in ('one', 'two')]
        with patch('gemini_cli.backends.local.stream_events', return_value=iter(calls)), \
                patch('gemini_cli.backends.local.to_gemini', side_effect=lambda rows: rows) as converted:
            list(self.backend.stream_chat(request).events)
            self.assertEqual(len(converted.call_args.args[0]), 25)
        active = [{'role': 'user', 'content': 'same question'}] + [dict(call, role='model') for call in calls]
        active += [{'role': 'tool', 'name': 'read_file_lines', 'content': 'private', 'call_id': call}
                   for call in ('one', 'two')]
        followup = self.payload(message='', history=active, continue_after_tool=True, turn_id=turn)
        with patch('gemini_cli.backends.local.stream_events', return_value=iter([
                {'type': 'text', 'content': 'finished'}])), \
                patch('gemini_cli.backends.local.to_gemini', side_effect=lambda rows: rows) as converted:
            list(self.backend.stream_chat(followup).events)
            self.assertEqual(len(converted.call_args.args[0]), 29)
        saved = self.backend.chats.read(self.chat)
        self.assertEqual([row['call_id'] for row in saved[-5:-1]], ['one', 'two', 'one', 'two'])
        self.assertEqual(saved[-4]['thought_signature'], 'sig')
        self.assertNotIn('private', str(saved))
        self.assertEqual([row['event_index'] for row in saved[-3:]], [0, 1, 2])

    def test_oversize_history_is_explicitly_rejected(self):
        with patch('gemini_cli.backends.local.stream_events') as provider:
            response = self.backend.stream_chat(self.payload(history=[{'role': 'user', 'content': 'x'}] * 1001))
        self.assertEqual(response.status_code, 400)
        provider.assert_not_called()

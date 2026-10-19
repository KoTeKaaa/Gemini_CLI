from pathlib import Path
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from gemini_cli.backends.local import LocalBackend


class LocalHistoryAPITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.provider = Mock()
        self.provider.models.get.return_value = SimpleNamespace(input_token_limit=10000, output_token_limit=1000)
        self.backend = LocalBackend('private-key-' + str(uuid4()), Path(self.directory.name),
                                    profile='profile', provider=self.provider)
        self.addCleanup(self.backend.close)
        self.chat = self.backend.create_chat('chat')['id']
        self.rows = []
        for turn in range(5):
            for ordinal, role in enumerate(('user', 'model')):
                self.rows.append({'id': str(uuid4()), 'role': role, 'content': f'{turn}:{role}',
                    'turn_id': str(uuid4()) if role == 'user' else self.rows[-1]['turn_id'],
                    'status': 'completed', 'request_id': str(turn), 'event_index': ordinal})
        self.backend.chats.append(self.chat, self.rows)

    def test_context_counts_actual_contents_instruction_and_tools_without_generation(self):
        payload = {'chat_id': self.chat, 'message': 'next', 'supported_tools': ['execute_command']}
        with patch('gemini_cli.backends.local.to_gemini', side_effect=lambda rows: rows) as convert:
            info = self.backend.context_info(payload)
        self.assertEqual(len(convert.call_args.args[0]), 11)
        self.assertEqual(info['input_token_limit'], 10000)
        self.assertEqual(info['output_token_limit'], 1000)
        self.assertEqual(info['source'], 'estimate')
        self.assertIsInstance(info['input_tokens'], int)
        self.provider.models.generate_content_stream.assert_not_called()
        self.assertNotIn(self.backend.api_key, str(self.backend._model_cache_scope))
        self.provider.models.count_tokens.return_value = SimpleNamespace(total_tokens=123)
        counted = self.backend.context_info(dict(payload, refresh=True))
        self.assertEqual(counted['input_tokens'], 123)
        config = self.provider.models.count_tokens.call_args.kwargs['config']
        self.assertTrue(config['system_instruction'])
        self.assertTrue(config['tools'])

    def test_compact_success_persists_summary_without_rewriting_history_and_forks_prefix(self):
        before = self.backend.get_history(self.chat)
        with patch('gemini_cli.backends.local.stream_events', return_value=iter([
                {'type': 'text', 'content': 'safe summary'}])) as generate:
            result = self.backend.compact_chat({'chat_id': self.chat})
        self.assertEqual(result['reason'], 'ready')
        self.assertEqual(self.backend.chats.metadata(self.chat)['summary'], 'safe summary')
        self.assertEqual(self.backend.get_history(self.chat), before)
        self.assertEqual(generate.call_args.kwargs['supported_tools'], [])
        self.assertEqual(generate.call_args.kwargs['permitted_tools'], set())
        forked = self.backend.fork_chat(self.chat, 'fork')
        self.assertEqual(len(self.backend.get_history(forked['id'])), 10)
        self.assertEqual(forked['fork_parent_id'], self.chat)

    def test_cancel_and_provider_error_retain_prior_summary(self):
        self.backend.chats.set_summary(self.chat, 'old', self.rows[1]['id'])
        for kind in ('cancel', 'error'):
            cancelled = Event()
            def events(*args, **kwargs):
                yield {'type': 'text', 'content': 'new'}
                if kind == 'cancel':
                    cancelled.set()
                else:
                    yield {'type': 'error', 'content': 'failed'}
            with self.subTest(kind=kind), patch('gemini_cli.backends.local.stream_events', side_effect=events):
                result = self.backend.compact_chat({'chat_id': self.chat}, cancelled.is_set)
            self.assertIsNone(result['summary'])
            self.assertEqual(self.backend.chats.metadata(self.chat)['summary'], 'old')
            self.assertEqual(result['reason'], 'cancelled' if kind == 'cancel' else 'summary_failed')

    def test_temp_compaction_returns_candidate_and_omits_private_tool_content(self):
        rows = list(self.rows)
        rows[1:1] = [{'role': 'model', 'name': 'execute_command', 'content': 'secret args',
                      'args': {'command': 'private command'}, 'call_id': 'one', 'status': 'completed'},
                     {'role': 'tool', 'name': 'execute_command', 'content': 'private output',
                      'call_id': 'one', 'status': 'completed'}]
        before = self.backend.chats.metadata(self.chat)
        with patch('gemini_cli.backends.local.to_gemini', side_effect=lambda history: history) as convert, \
                patch('gemini_cli.backends.local.stream_events', return_value=iter([
                    {'type': 'text', 'content': 'temporary summary'}])):
            result = self.backend.compact_chat({'history': rows})
        source = str(convert.call_args.args[0])
        self.assertNotIn('private command', source)
        self.assertNotIn('private output', source)
        self.assertNotIn('secret args', source)
        self.assertEqual(result['boundary_id'], self.rows[5]['id'])
        self.assertEqual(self.backend.chats.metadata(self.chat), before)
        with self.assertRaises(ValueError):
            self.backend.compact_chat({'history': self.rows * 101})

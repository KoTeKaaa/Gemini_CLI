import copy
import json
import unittest
from unittest.mock import Mock

from gemini_cli.runtime.compaction import (
    MAX_SUMMARY_CHARS, prepare_compaction, run_compaction, should_auto_compact)


def history(turns=4):
    return [row for index in range(turns) for row in (
        {'id': f'user-{index}', 'role': 'user', 'content': 'question'},
        {'id': f'answer-{index}', 'role': 'model', 'content': 'answer'})]


class CompactionTests(unittest.TestCase):
    def test_whole_turn_boundary_and_original_preserved(self):
        original = history()
        snapshot = copy.deepcopy(original)
        result = prepare_compaction(original)
        self.assertEqual(result['boundary_id'], 'answer-1')
        self.assertEqual(result['tail'], original[4:])
        result['tail'][0]['content'] = 'changed'
        self.assertEqual(original, snapshot)
        self.assertEqual(len(result['source']), 4)

    def test_tools_and_images_never_enter_summary(self):
        original = history()
        original[0]['images'] = [{'data': b'private image'}]
        original[1:1] = [
            {'role': 'model', 'name': 'execute_command', 'args': {'command': 'private args'}, 'call_id': 'c'},
            {'role': 'tool', 'name': 'execute_command', 'content': 'private output', 'call_id': 'c'}]
        source = json.dumps(prepare_compaction(original)['source'])
        self.assertNotIn('private', source)
        self.assertNotIn('images', source)
        self.assertIn('tool details omitted', source)

    def test_pending_batch_is_not_repaired_into_completed_turn(self):
        original = history()
        original[1:1] = [{'role': 'model', 'name': 'read_file_lines', 'args': {'path': 'file'}, 'call_id': 'c'}]
        self.assertEqual(prepare_compaction(original)['reason'], 'no_completed_boundary')

    def test_ambiguous_batch_results_cannot_complete_turn(self):
        original = history()
        original[1:1] = [
            {'role': 'model', 'name': 'command', 'call_id': 'a'},
            {'role': 'model', 'name': 'command', 'call_id': 'b'},
            {'role': 'tool', 'name': 'command'},
            {'role': 'tool', 'name': 'command'}]
        self.assertIsNone(prepare_compaction(original)['boundary_id'])

    def test_active_and_failed_prefixes_are_not_crossed(self):
        for status in ('running', 'cancelled', 'failed'):
            original = history()
            original[1]['status'] = status
            self.assertIsNone(prepare_compaction(original)['boundary_id'])
        original = history(5)
        original[3]['status'] = 'running'
        self.assertEqual(prepare_compaction(original)['boundary_id'], 'answer-0')

    def test_missing_id_and_nonfinal_model_are_not_boundaries(self):
        original = history()
        original[3].pop('id')
        self.assertIsNone(prepare_compaction(original)['boundary_id'])
        original = history()
        original[1]['content'] = ''
        self.assertIsNone(prepare_compaction(original)['boundary_id'])

    def test_candidate_and_cancellation_do_not_mutate_input(self):
        original = history()
        snapshot = copy.deepcopy(original)
        stopped = False
        def summarize(source):
            nonlocal stopped
            source[0]['content'] = 'mutated'
            stopped = True
            return 'summary'
        result = run_compaction(original, summarize, cancelled=lambda: stopped)
        self.assertEqual(result['reason'], 'cancelled')
        self.assertIsNone(result['summary'])
        self.assertEqual(original, snapshot)
        result = run_compaction(original, lambda source: ' summary ')
        self.assertEqual(result['summary'], 'summary')
        self.assertEqual(result['boundary_id'], 'answer-1')

    def test_failures_bounded_summary_and_caller_retry_block(self):
        for response in ('', ' ' * 3, None, 'x' * (MAX_SUMMARY_CHARS + 1)):
            result = run_compaction(history(), lambda source: response)
            self.assertEqual(result['reason'], 'invalid_summary')
        callback = Mock(side_effect=RuntimeError('private error'))
        failure = run_compaction(history(), callback)
        self.assertEqual(failure['reason'], 'summary_failed')
        result = run_compaction(history(), callback, blocked_fingerprint=failure['fingerprint'])
        self.assertEqual(result['reason'], 'previous_failure')
        self.assertEqual(callback.call_count, 1)
        self.assertNotIn('private', str(result))

    def test_cancelled_before_call(self):
        callback = Mock()
        result = run_compaction(history(), callback, cancelled=lambda: True)
        self.assertEqual(result['reason'], 'cancelled')
        callback.assert_not_called()

    def test_auto_uses_actual_limits_and_reserve(self):
        info = {'input_tokens': 60, 'input_token_limit': 100, 'output_token_limit': 10}
        self.assertFalse(should_auto_compact(info))
        self.assertTrue(should_auto_compact(info, 10))
        self.assertTrue(should_auto_compact(info, 'a' * 40))
        self.assertFalse(should_auto_compact({**info, 'input_token_limit': None}, 100))
        self.assertFalse(should_auto_compact({**info, 'has_unmeasured_media': True}, 100))
        self.assertFalse(should_auto_compact(info, {'input_tokens': None}))

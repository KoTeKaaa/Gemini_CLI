import importlib
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from gemini_cli.client.completion import COMMANDS
from gemini_cli.runtime.compaction import completed_boundaries


class UIContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"HOME": home}):
            cls.app = importlib.import_module("main")

    def test_chat_search_explicit_no_extra_api_calls(self):
        client = Mock()
        client.get_chats.return_value = [
            {"id": "a", "title": "Same", "created_at": "2026-01-01"},
            {"id": "b", "title": "Other", "created_at": "2026-01-01"}]
        with patch.object(self.app, "radiolist_dialog") as dialog, patch("builtins.input", return_value="same") as prompt:
            dialog.return_value.run.side_effect = ["search", "a"]
            self.assertEqual(self.app.show_chat_menu(client, current_id="a"), ("a", False))
            values = dialog.call_args.kwargs["values"]
            self.assertIn("текущий", values[-1][1])
            self.assertNotIn("b", [key for key, _ in values])
            prompt.assert_called_once()
            client.get_chats.assert_called_once()
        with patch.object(self.app, "radiolist_dialog") as dialog, patch("builtins.input") as prompt:
            dialog.return_value.run.return_value = "temporary"
            self.assertEqual(self.app.show_chat_menu(client), (None, True))
            prompt.assert_not_called()

    def test_explicit_history_limit_and_summary_payload(self):
        rows = [{"id": "event", "role": "user", "content": "question"}]
        summary = {"summary": "context", "boundary_id": "event"}
        payload = self.app.build_stream_payload(rows, None, "model", True, summary=summary)
        self.assertEqual(payload["summary_boundary"], "event")
        with self.assertRaises(ValueError):
            self.app.build_stream_payload(rows * 1001, None, "model", True)
        for command in ("/clear", "/compact", "/fork"):
            self.assertIn(command, COMMANDS)

    def test_compact_cancellation_drops_late_candidate(self):
        backend = Mock()
        with patch.object(self.app, "WorkView"), patch.object(self.app, "run_cancellable", side_effect=InterruptedError):
            result = self.app.compact_context(backend, [], None, "model")
        self.assertEqual(result["reason"], "cancelled")
        self.assertIsNone(result["summary"])

    def test_fork_boundaries_only_explicit_completed_turns(self):
        rows = [{"role": "user", "content": "q", "id": "u", "turn_id": "turn", "status": "completed"},
                {"role": "model", "content": "a", "id": "m", "turn_id": "turn", "status": "completed"}]
        self.assertEqual(completed_boundaries(rows), [rows[1]])
        rows[1]["status"] = "running"
        self.assertEqual(completed_boundaries(rows), [])
        rows[1]["status"] = "legacy"
        self.assertEqual(completed_boundaries(rows), [])

    def test_main_clear_only_temporary_preserves_model_and_cwd(self):
        from gemini_cli.client.draft import Draft
        for selected, expected in [((None, True), ""), (("saved", False), "draft")]:
            draft = Draft("draft")
            draft.add_text_file("file", "contents")
            backend = Mock(mode="local")
            backend.get_history.return_value = []
            with patch.object(self.app, "show_chat_menu", return_value=selected), \
                 patch.object(self.app, "Draft", side_effect=[draft, Draft()]), \
                 patch.object(self.app, "PromptSession") as session, \
                 patch.object(self.app, "print_banner"), patch.object(self.app.console, "print"):
                session.return_value.prompt.side_effect = ["/clear", "exit"]
                self.app.main(backend)
                second = session.return_value.prompt.call_args_list[1]
                self.assertEqual(second.kwargs["default"], expected)
                self.assertIn("gemini-3.5-flash-lite", str(second.args[0]))
                backend.stream_chat.assert_not_called()
                backend.delete_chat.assert_not_called()

    def test_chat_switch_restores_unsent_draft(self):
        from gemini_cli.client.draft import Draft
        draft = Draft("unfinished")
        draft.add_text_file("file", "contents")
        backend = Mock(mode="local")
        backend.get_history.return_value = []
        with patch.object(self.app, "show_chat_menu", side_effect=[(None, True), ("saved", False), (None, True)]), \
             patch.object(self.app, "Draft", side_effect=[draft, Draft()]), \
             patch.object(self.app, "PromptSession") as session, \
             patch.object(self.app, "print_banner"), patch.object(self.app.console, "print"):
            session.return_value.prompt.side_effect = ["/chat", "/chat", "exit"]
            self.app.main(backend)
            self.assertEqual([call.kwargs["default"] for call in session.return_value.prompt.call_args_list],
                             ["unfinished", "", "unfinished"])
            backend.stream_chat.assert_not_called()

    def test_temporary_turn_has_stable_completed_ids(self):
        from uuid import UUID
        backend = Mock(mode="local")
        with patch.object(self.app, "show_chat_menu", return_value=(None, True)), \
             patch.object(self.app, "PromptSession") as session, \
             patch.object(self.app, "print_banner"), patch.object(self.app.console, "print"), \
             patch.object(self.app.console, "rule"), patch.object(self.app, "open_stream") as stream, \
             patch.object(self.app, "WorkView"), \
             patch.object(self.app, "display_stream_response", return_value=("answer", [])):
            stream.return_value.status_code = 200
            session.return_value.prompt.side_effect = ["first", "second", "exit"]
            self.app.main(backend)
            rows = stream.call_args.args[1]["history"]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["turn_id"], rows[1]["turn_id"])
            self.assertEqual([row["status"] for row in rows], ["completed", "completed"])
            self.assertNotEqual(rows[0]["id"], rows[1]["id"])
            for row in rows:
                UUID(row["id"])

    def test_fork_chooses_completed_boundary_and_never_replays(self):
        backend = Mock()
        backend.get_history.return_value = [
            {'role': role, 'content': text, 'id': event_id, 'turn_id': 'turn', 'status': 'completed'}
            for role, text, event_id in [('user', 'q', 'u'), ('model', 'a', 'm')]]
        backend.fork_chat.return_value = {'id': 'fork'}
        with patch.object(self.app, 'radiolist_dialog') as dialog, patch('builtins.input') as prompt:
            dialog.return_value.run.return_value = 0
            self.assertEqual(self.app.fork_context(backend, 'source', 'New title'), {'id': 'fork'})
            backend.fork_chat.assert_called_once_with('source', 'New title', 'm')
            self.assertEqual(dialog.call_args.kwargs['default'], 0)
            prompt.assert_not_called()
            backend.stream_chat.assert_not_called()

    def test_fork_cancel_does_not_create_chat(self):
        backend = Mock()
        backend.get_history.return_value = [
            {'role': role, 'content': 'text', 'id': role, 'turn_id': 'turn', 'status': 'completed'}
            for role in ['user', 'model']]
        with patch.object(self.app, 'radiolist_dialog') as dialog:
            dialog.return_value.run.return_value = None
            self.assertIsNone(self.app.fork_context(backend, 'source', 'title'))
            backend.fork_chat.assert_not_called()

    def test_manual_compact_keeps_full_archive_and_sends_summary(self):
        backend = Mock(mode='local')
        candidate = {'summary': 'safe context', 'boundary_id': 'boundary', 'reason': 'ready'}
        with patch.object(self.app, 'show_chat_menu', return_value=(None, True)), \
             patch.object(self.app, 'PromptSession') as session, \
             patch.object(self.app, 'print_banner'), patch.object(self.app.console, 'print'), \
             patch.object(self.app.console, 'rule'), patch.object(self.app, 'WorkView'), \
             patch.object(self.app, 'open_stream') as stream, \
             patch.object(self.app, 'display_stream_response', return_value=('answer', [])), \
             patch.object(self.app, 'compact_context', side_effect=lambda client, rows, *args: {**candidate, 'boundary_id': rows[1]['id']}) as compact:
            stream.return_value.status_code = 200
            session.return_value.prompt.side_effect = ['first', '/compact', 'second', 'exit']
            self.app.main(backend)
            self.assertEqual(len(compact.call_args.args[1]), 4)
            self.assertEqual(stream.call_args.args[1]['summary'], 'safe context')
            self.assertEqual(stream.call_args.args[1]['summary_boundary'], compact.call_args.args[1][1]['id'])

    def test_temporary_fork_refused_without_backend_call(self):
        backend = Mock(mode='local')
        with patch.object(self.app, 'show_chat_menu', return_value=(None, True)), \
             patch.object(self.app, 'PromptSession') as session, \
             patch.object(self.app, 'print_banner'), patch.object(self.app.console, 'print'):
            session.return_value.prompt.side_effect = ['/fork title', 'exit']
            self.app.main(backend)
            backend.fork_chat.assert_not_called()
            backend.stream_chat.assert_not_called()

    def test_wire_summary_tail_keeps_full_archive(self):
        rows = [{'id': str(index), 'role': 'model', 'content': 'answer'} for index in range(1200)]
        rows[-1] = {'id': 'last', 'role': 'user', 'content': 'question'}
        summary = {'summary': 'old context', 'boundary_id': '1100'}
        result = self.app.build_stream_payload(rows, None, 'model', True, summary=summary)
        self.assertEqual(len(rows), 1200)
        self.assertEqual(result['history'][0]['id'], '1100')
        self.assertEqual(len(result['history']), 99)
        self.assertEqual(len(self.app.context_payload(rows, 'saved', 'model')['history']), 1000)
        self.assertEqual(len(self.app.context_payload(rows, None, 'model')['history']), 1200)
        with self.assertRaises(ValueError):
            self.app.context_payload(rows * 9, None, 'model')

    def test_persistent_active_turn_over_limit_is_not_split(self):
        rows = [{'role': 'user', 'content': 'question'}] + [
            {'role': 'tool', 'content': 'result'} for _ in range(1000)]
        with self.assertRaises(ValueError):
            self.app.build_stream_payload(rows, 'saved', 'model', False)

    def test_startup_history_error_preserves_chat_and_draft(self):
        backend = Mock(mode='local')
        backend.get_history.side_effect = ValueError('unavailable')
        with patch.object(self.app, 'show_chat_menu', return_value=('saved', False)), \
             patch.object(self.app, 'PromptSession') as session, \
             patch.object(self.app, 'print_banner'), patch.object(self.app.console, 'print') as output:
            session.return_value.prompt.side_effect = ['exit']
            self.app.main(backend)
            self.assertTrue(any('Не удалось загрузить историю' in getattr(getattr(call.args[0], 'renderable', None), 'plain', '') for call in output.call_args_list))
            backend.stream_chat.assert_not_called()

    def test_unknown_context_never_attempts_auto_compact(self):
        backend = Mock(mode='local')
        with patch.object(self.app, 'show_chat_menu', return_value=(None, True)), \
             patch.object(self.app, 'PromptSession') as session, \
             patch.object(self.app, 'print_banner'), patch.object(self.app.console, 'print'), \
             patch.object(self.app.console, 'rule'), patch.object(self.app, 'WorkView'), \
             patch.object(self.app, 'open_stream') as stream, \
             patch.object(self.app, 'display_stream_response', return_value=('answer', [])), \
             patch.object(self.app, 'inspect_context', return_value={'input_token_limit': None}), \
             patch.object(self.app, 'compact_context') as compact:
            stream.return_value.status_code = 200
            session.return_value.prompt.side_effect = ['question', 'exit']
            self.app.main(backend)
            compact.assert_not_called()

    def test_auto_failure_fingerprint_and_cancel_no_send(self):
        backend = Mock(mode='local')
        info = {'input_tokens': 80, 'input_token_limit': 100, 'output_token_limit': 10}
        results = [{'reason': 'summary_failed', 'fingerprint': 'failed'}, {'reason': 'cancelled'}]
        with patch.object(self.app, 'show_chat_menu', return_value=(None, True)), \
             patch.object(self.app, 'PromptSession') as session, \
             patch.object(self.app, 'print_banner'), patch.object(self.app.console, 'print'), \
             patch.object(self.app.console, 'rule'), patch.object(self.app, 'WorkView'), \
             patch.object(self.app, 'open_stream') as stream, \
             patch.object(self.app, 'display_stream_response', return_value=('answer', [])), \
             patch.object(self.app, 'inspect_context', return_value=info), \
             patch.object(self.app, 'compact_context', side_effect=results) as compact:
            stream.return_value.status_code = 200
            session.return_value.prompt.side_effect = ['first', 'second', 'exit']
            self.app.main(backend)
            self.assertEqual(stream.call_count, 1)
            self.assertEqual(compact.call_args.kwargs['blocked_fingerprint'], 'failed')

    def test_failed_prompt_restore_requires_confirmation_and_ignores_images(self):
        from gemini_cli.runtime.attachments import MARKER
        backend = Mock()
        completed = [
            {'role': role, 'content': 'text', 'id': event_id, 'turn_id': 'turn', 'status': 'completed'}
            for role, event_id in [('user', 'u'), ('model', 'm')]]
        backend.get_history.return_value = completed + [
            {'role': 'user', 'id': 'failed', 'status': 'failed', 'content': 'retry text' + MARKER + '[image metadata]',
             'images': [{'data': b'private image'}]},
            {'role': 'tool', 'status': 'failed', 'content': 'private output'}]
        backend.fork_chat.return_value = {'id': 'fork'}
        for confirm in [False, True]:
            with patch.object(self.app, 'radiolist_dialog') as boundary, \
                 patch.object(self.app, 'yes_no_dialog') as prompt:
                boundary.return_value.run.return_value = 0
                prompt.return_value.run.return_value = confirm
                result = self.app.fork_context(backend, 'source', 'title')
                self.assertEqual(result.get('_restore_prompt'), 'retry text' if confirm else None)
                prompt.assert_called_once()
                self.assertNotIn('private', str(result))
                backend.stream_chat.assert_not_called()
        backend.get_history.return_value = completed
        with patch.object(self.app, 'radiolist_dialog') as boundary, patch.object(self.app, 'yes_no_dialog') as prompt:
            boundary.return_value.run.return_value = 0
            self.app.fork_context(backend, 'source', 'title')
            prompt.assert_not_called()

    def test_failed_prompt_must_be_after_boundary_and_explicitly_failed(self):
        rows = [{'id': 'before', 'role': 'user', 'content': 'old', 'status': 'failed'},
                {'id': 'boundary', 'role': 'model', 'content': 'answer', 'status': 'completed'},
                {'id': 'later', 'role': 'user', 'content': 'normal', 'status': 'completed'}]
        self.assertIsNone(self.app.failed_prompt_after(rows, 'boundary'))
        rows[-1]['status'] = 'cancelled'
        self.assertEqual(self.app.failed_prompt_after(rows, 'boundary'), 'normal')
        self.assertIsNone(self.app.failed_prompt_after(rows, 'missing'))

    def test_fork_draft_restore_preserves_source_unsent_draft_and_never_sends(self):
        from gemini_cli.client.draft import Draft
        draft = Draft('unsent source')
        draft.add_text_file('source.txt', 'source attachment')
        backend = Mock(mode='local')
        backend.get_history.return_value = []
        with patch.object(self.app, 'show_chat_menu', side_effect=[('source', False), ('source', False)]), \
             patch.object(self.app, 'Draft', side_effect=[draft, Draft()]), \
             patch.object(self.app, 'fork_context', return_value={'id': 'fork', '_restore_prompt': 'retry text'}), \
             patch.object(self.app, 'PromptSession') as session, \
             patch.object(self.app, 'print_banner'), patch.object(self.app.console, 'print'):
            session.return_value.prompt.side_effect = ['/fork title', '/chat', 'exit']
            self.app.main(backend)
            self.assertEqual([call.kwargs['default'] for call in session.return_value.prompt.call_args_list],
                             ['unsent source', 'retry text', 'unsent source'])
            self.assertEqual(draft.files, [('source.txt', 'source attachment')])
            backend.stream_chat.assert_not_called()

    def test_fork_restores_prompt_when_later_continuation_failed(self):
        rows = [{'id': 'boundary', 'role': 'model', 'status': 'completed', 'content': 'done'},
                {'id': 'request', 'role': 'user', 'status': 'completed', 'content': 'Retry this task'},
                {'role': 'model', 'status': 'completed', 'name': 'read_file_lines', 'content': 'call'},
                {'role': 'tool', 'status': 'failed', 'content': 'interrupted'}]
        self.assertEqual(self.app.failed_prompt_after(rows, 'boundary'), 'Retry this task')

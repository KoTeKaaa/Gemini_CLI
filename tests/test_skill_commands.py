from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from prompt_toolkit.document import Document
from rich.console import Console
from gemini_cli.client.completion import InputCompleter
from gemini_cli.client.skill_commands import Selection, command


class SkillCommandsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'skills' / 'review' / 'SKILL.md'
        self.path.parent.mkdir(parents=True)
        self.path.write_text('---\nname: review\ndescription: Review code\n---\nPRIVATE_BODY')
        config = self.root / 'skills.json'
        config.write_text(json.dumps({'version': 1, 'directories': [str(self.root / 'skills')]}))
        self.selection = Selection(config).bind(('local', 'chat', 'workspace'))
        self.output = StringIO()
        self.console = Console(file=self.output, width=100)

    def test_list_select_disable_and_read_failure(self):
        command('/skill', self.selection, console=self.console)
        self.assertIn('review', self.output.getvalue())
        self.assertNotIn('PRIVATE_BODY', self.output.getvalue())
        self.assertIsNone(self.selection.payload())
        command('/skill use review', self.selection, console=self.console)
        self.assertIn('PRIVATE_BODY', self.selection.payload()['content'])
        snapshot = self.selection.payload()
        snapshot['content'] = 'changed'
        self.assertNotEqual(snapshot, self.selection.payload())
        self.path.unlink()
        command('/skill use review', self.selection, console=self.console)
        self.assertIn('не изменён', self.output.getvalue())
        self.assertIn('PRIVATE_BODY', self.selection.payload()['content'])
        command('/skill off', self.selection, console=self.console)
        self.assertIsNone(self.selection.payload())
        command('/skill nonsense', self.selection, console=self.console)
        self.assertIn('/skill use', self.output.getvalue())

    def test_selection_not_inherited_by_chat_account_backend_or_workspace(self):
        for scope in (('local', 'new', 'workspace'), ('remote', 'chat', 'workspace'),
                      ('account-b', 'chat', 'workspace'), ('local', 'chat', 'other')):
            self.selection.choose('review')
            self.selection.bind(scope)
            self.assertIsNone(self.selection.payload())

    def test_completion_names_without_body(self):
        self.path.write_bytes(self.path.read_bytes() + b'\xff')
        completer = InputCompleter(lambda: '.', skill_choices=self.selection.choices)
        def choices(text):
            return [c.text for c in completer.get_completions(Document(text), None)]
        self.assertEqual(choices('/ski'), ['/skill'])
        self.assertEqual(choices('/skill '), ['list', 'use', 'off'])
        self.assertEqual(choices('/skill use re'), ['review'])
        self.assertEqual(choices('/skill unknown '), [])

    def test_payload_and_status_contain_only_selected_skill(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {'HOME': str(self.root), 'USERPROFILE': str(self.root)}):
            import main
        history = [{'role': 'user', 'content': 'task'}]
        self.assertNotIn('skill_context', main.build_stream_payload(history, None, 'test', True))
        self.selection.choose('review')
        context = self.selection.payload()
        payload = main.build_stream_payload(history, None, 'test', True, skill=context)
        status = main.status_context_payload([], None, 'test', skill=context)
        self.assertEqual(payload['skill_context'], status['skill_context'])
        self.assertNotIn('PRIVATE_BODY', str(history))
        self.assertNotIn('PRIVATE_BODY', str(payload['history']))

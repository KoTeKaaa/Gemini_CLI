from io import StringIO
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch

from prompt_toolkit.document import Document
from rich.console import Console
from gemini_cli.client.integration_help import SKILL_HELP, MCP_HELP, show_guide
from gemini_cli.client.completion import InputCompleter


class IntegrationHelpTest(unittest.TestCase):
    def test_help_never_reads_configuration_or_starts_connections(self):
        from gemini_cli.client.mcp_commands import command as mcp
        from gemini_cli.client.skill_commands import command as skill
        console = Console(file=StringIO())
        factory = Mock(side_effect=AssertionError('No configuration/network for help'))
        with patch('gemini_cli.client.integration_help.view_text') as viewer:
            mcp('/mcp help', console=console, read_secret=factory, manager_factory=factory)
            skill('/skill help', None, console=console)
            self.assertEqual([c.args[0] for c in viewer.call_args_list], [MCP_HELP, SKILL_HELP])
            self.assertIn('Esc', viewer.call_args.kwargs['title'])
        factory.assert_not_called()
        self.assertFalse(console.file.getvalue())

    def test_examples_parse_and_mcp_configuration_is_supported(self):
        from gemini_cli.integrations.mcp.config import load_connections
        from gemini_cli.integrations.skills import metadata
        examples = [json.loads(re.search(r'(?ms)^\{\n.*?^\}', text).group()) for text in (SKILL_HELP, MCP_HELP)]
        self.assertEqual(examples[0]['directories'], ['/home/example/my-skills'])
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'mcp.json').write_text(json.dumps(examples[1]))
            self.assertEqual(load_connections(Path(tmp))['github'].tools, ('get_file_contents',))
        frontmatter = re.search(r'(?ms)^---\n.*?^---\n', SKILL_HELP).group()
        self.assertEqual(metadata(frontmatter, 'code-review')['name'], 'code-review')

    def test_help_completes_without_enumerating_connections_or_skills(self):
        forbidden = Mock(side_effect=AssertionError('Help needs no discovery'))
        completer = InputCompleter(lambda: '.', mcp_choices=forbidden, skill_choices=forbidden)
        for text in ('/mcp h', '/skill h'):
            self.assertEqual([c.text for c in completer.get_completions(Document(text), None)], ['help'])
        for text in ('/mcp help ', '/skill help ', '/skills'):
            self.assertEqual(list(completer.get_completions(Document(text), None)), [])
        forbidden.assert_not_called()

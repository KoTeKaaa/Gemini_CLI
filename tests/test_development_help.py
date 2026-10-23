import unittest
from unittest.mock import Mock
from prompt_toolkit.document import Document
from gemini_cli.client.completion import InputCompleter
from gemini_cli.client.development_help import HELP, command
from gemini_cli.backends.genai import provider_tools
from gemini_cli.tools.definitions import CLIENT_NAMES


class DevelopmentHelpTests(unittest.TestCase):
    def test_help_completion_errors_and_provider_declarations(self):
        viewer, console = Mock(), Mock()
        command('/dev help', console=console, viewer=viewer)
        viewer.assert_called_once()
        self.assertIn('GEMINI_CLI_PYLSP', viewer.call_args.args[0])
        self.assertIn('PowerShell', HELP)
        command('/dev unknown', console=console, viewer=viewer)
        console.print.assert_called_once()
        completer = InputCompleter(lambda: '.')
        self.assertEqual([x.text for x in completer.get_completions(Document('/dev h'), None)], ['help'])
        names = {row.name for row in provider_tools(list(CLIENT_NAMES), set(CLIENT_NAMES))[0].function_declarations}
        self.assertTrue({'python_symbols', 'python_lsp', 'run_tests', 'affected_tests',
                         'git_read', 'git_commit', 'github_pr'} <= names)

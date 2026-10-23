from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from prompt_toolkit.document import Document
from gemini_cli.client.document_help import command, HELP
from gemini_cli.client.completion import InputCompleter


class DocumentHelpTests(unittest.TestCase):
    def test_static_help_and_error(self):
        viewer, console = Mock(), Mock()
        command('/doc help', viewer=viewer, console=console)
        viewer.assert_called_once()
        self.assertIn('6000', HELP)
        command('/doc wrong', viewer=viewer, console=console)
        console.print.assert_called_once()

    def test_completion_templates_without_parser_or_content_read(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'report.pdf').write_bytes(b'not parsed')
            completer = InputCompleter(lambda: root)
            def choices(text): return [c.text for c in completer.get_completions(Document(text), None)]
            self.assertIn('help', choices('/doc h'))
            self.assertIn('@report.pdf#pages=1', choices('@rep'))
            self.assertIn('@report.pdf#pages=1-3', choices('@report.pdf#p'))
            self.assertTrue(completer.snapshots)

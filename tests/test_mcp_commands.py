import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from gemini_cli.client.mcp_commands import command
from gemini_cli.integrations.mcp.manager import Manager
from tests.test_mcp_runner import FakeSession


class MCPCommandsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'HOME': directory}):
            import main

    def test_commands_toggle_next_payload_without_llm(self):
        import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'mcp.json').write_text(json.dumps({'version': 1, 'servers': [
                {'name': 'demo', 'transport': 'stdio', 'command': 'fixture'}]}))
            manager = Manager(root, 'account', session_factory=FakeSession)
            console = Mock()
            history = [{'role': 'user', 'content': 'hello'}]
            command('/mcp enable demo', manager, console=console, read_secret=Mock())
            payload = main.build_stream_payload(history, None, 'gemini-3.5-flash-lite', True, mcp=manager)
            self.assertEqual(len(payload['mcp_tools']), 1)
            status = main.status_context_payload(history, None, 'gemini-3.5-flash-lite', mcp=manager)
            self.assertEqual(status['mcp_tools'], payload['mcp_tools'])
            command('/mcp disable demo', manager, console=console, read_secret=Mock())
            self.assertNotIn('mcp_tools', main.build_stream_payload(history, None, 'gemini-3.5-flash-lite', True, mcp=manager))
            command('/mcp tools missing', manager, console=console, read_secret=Mock())
            self.assertIn('/mcp check', str(console.print.call_args.args[0].renderable))
            manager.close()

    def test_untrusted_tool_labels_cannot_emit_terminal_controls(self):
        import io
        from rich.console import Console
        from unittest.mock import patch
        from gemini_cli.client.mcp_commands import approve_call
        output = io.StringIO()
        with patch('builtins.input', return_value='n'):
            self.assertFalse(approve_call(Console(file=output, color_system=None),
                'demo', 'tool\x1b[2J', {'path': 'left\u202eright'}))
        self.assertNotIn('\x1b', output.getvalue())
        self.assertNotIn('\u202e', output.getvalue())

    def test_help_and_completion(self):
        from gemini_cli.client.completion import COMMANDS
        self.assertIn('/mcp', COMMANDS)
        import inspect, main
        self.assertIn('table.add_row("/mcp"', inspect.getsource(main.main))

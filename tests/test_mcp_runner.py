import json
import logging
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from gemini_cli.integrations.mcp.manager import Manager
from gemini_cli.client.tool_runner import execute_tool_calls
from gemini_cli.protocol.mcp import tool_name
from gemini_cli.runtime.history import persistent_history_rows


class FakeSession:
    closed = False
    calls = []
    def __init__(self, *args, **kwargs):
        pass
    def request(self, operation, *args, **kwargs):
        if operation == 'list':
            return {'tools': [{'name': 'echo', 'inputSchema': {'type': 'object'}}]}
        self.calls.append(args)
        return 'PRIVATE-RESULT'
    def close(self):
        self.closed = True


class MCPRunnerTest(unittest.TestCase):
    def test_mixed_batch_refusal_disable_and_private_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'mcp.json').write_text(json.dumps({'version': 1, 'servers': [
                {'name': 'demo', 'transport': 'stdio', 'command': 'fixture'}]}))
            manager = Manager(root, 'account', session_factory=FakeSession)
            self.assertEqual(manager.declarations(), [])
            manager.enable('demo')
            name = tool_name('demo', 'echo')
            history = [{'role': 'user', 'content': 'task'}]
            execute_tool_calls([{'name': n, 'args': {}, 'call_id': str(i), 'thought_signature': 'sig'}
                                for i, n in enumerate(('execute_command', name, 'read_url'))], history, '.',
                handlers={'execute_command': lambda *_: 'local', 'read_url': lambda *_: 'web',
                    name: lambda args, _: manager.call(name, args, approve=lambda *_: True)},
                logger=logging.getLogger('fixture'))
            self.assertEqual([r['call_id'] for r in history if r['role'] == 'tool'], ['0', '1', '2'])
            self.assertNotIn('PRIVATE-RESULT', json.dumps(persistent_history_rows(history)))
            self.assertIn('declined', manager.call(name, {}, approve=lambda *_: False))
            manager.disconnect('demo')
            self.assertEqual(manager.declarations(), [])
            self.assertIn('mcp_disabled', manager.call(name, {}, approve=lambda *_: True))
            manager.close()

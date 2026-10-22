import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gemini_cli.integrations.mcp.config import load_connections


class MCPConfigTest(unittest.TestCase):
    def load(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'mcp.json').write_text(json.dumps({'version': 1, 'servers': rows}))
            return load_connections(path)

    def test_explicit_only_no_process(self):
        with patch('subprocess.Popen', side_effect=AssertionError('must not launch')):
            config = self.load([{'name': 'demo', 'transport': 'stdio', 'command': 'absent-runtime'}])
        self.assertFalse(config['demo'].enabled)

    def test_no_secrets_unknown_or_duplicate_fields(self):
        base = {'name': 'demo', 'transport': 'stdio', 'command': 'x'}
        for rows in ([{**base, 'env': {'TOKEN': 'secret'}}], [base, base],
                     [{**base, 'timeout': True}], [{**base, 'args': 'bad'}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.load(rows)

    def test_http_validation(self):
        for url in ('https://u:p@example.com/mcp', 'https://example.com/?token=x', 'http://localhost/mcp'):
            with self.assertRaises(ValueError):
                self.load([{'name': 'x', 'transport': 'http', 'url': url}])
        self.assertTrue(self.load([{'name': 'x', 'transport': 'http',
                                    'url': 'http://127.0.0.1:8000/mcp', 'allow_private': True}]))

    def test_no_config_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_connections(Path(directory)), {})

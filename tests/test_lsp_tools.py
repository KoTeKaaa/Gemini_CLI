import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from gemini_cli.tools.local.lsp_tools import documents, locations, python_lsp, validate_versions


class LSPToolsTests(unittest.TestCase):
    def test_locations_filter_external_limit_and_changed_versions(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root, 'a.py'); file.write_text('def f(): pass\n')
            docs = documents(root)
            span = {'start': {'line': 0, 'character': 4}, 'end': {'line': 0, 'character': 5}}
            row = {'uri': file.as_uri(), 'range': span}
            result = locations([{'uri': 'https://example.com/x'}, row] * 101, root, docs)
            self.assertTrue(result['truncated'])
            self.assertEqual(len(result['data']['locations']), 100)
            self.assertGreater(result['data']['rejected'], 0)
            self.assertEqual(result['data']['locations'][0]['line'], 1)
            file.write_text('def g(): pass\n')
            with self.assertRaises(ValueError): validate_versions(root, docs)

    def test_no_lsp_and_unsaved_version(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'GEMINI_CLI_PYLSP': ''}):
            args = {'action': 'definition', 'filepath': 'a.py'}
            self.assertEqual(python_lsp(args, root, approve=lambda _: True)['error']['code'], 'unavailable')
            Path(root, 'a.py').write_text('x=1\n')
            with patch.dict('os.environ', {'GEMINI_CLI_PYLSP': str(Path(root, 'server'))}):
                args['expected_sha256'] = 'unsaved'
                self.assertEqual(python_lsp(args, root, approve=lambda _: True)['error']['code'], 'lsp_error')

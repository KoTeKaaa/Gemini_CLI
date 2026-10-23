import tempfile
import unittest
from pathlib import Path
from gemini_cli.tools.local.affected import affected_tests


class AffectedTests(unittest.TestCase):
    def test_direct_transitive_relative_and_configuration(self):
        with tempfile.TemporaryDirectory() as root:
            for name, code in {'pkg/__init__.py': '', 'pkg/core.py': 'x=1',
                               'pkg/bridge.py': 'from .core import x',
                               'tests/test_direct.py': 'from pkg import core',
                               'tests/test_indirect.py': 'import pkg.bridge',
                               'tests/test_other.py': 'import os'}.items():
                file = Path(root, name); file.parent.mkdir(exist_ok=True)
                file.write_text(code)
            result = affected_tests({'files': ['pkg/core.py']}, root, approve=lambda _: True)['data']
            self.assertEqual(result['suggested_modules'], ['tests.test_direct', 'tests.test_indirect'])
            self.assertFalse(result['complete'])
            result = affected_tests({'files': ['pyproject.toml', 'deleted.py']}, root, approve=lambda _: True)['data']
            self.assertEqual(len(result['uncertainty']), 2)
            self.assertIn('Полная', result['fallback'])

    def test_denial_and_dynamic_import_uncertainty(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'a.py').write_text('__import__("unknown")')
            args = {'files': ['a.py']}
            self.assertTrue(affected_tests(args, root, approve=lambda _: True)['data']['uncertainty'])
            self.assertEqual(affected_tests(args, root, approve=lambda _: False)['error']['code'], 'denied')

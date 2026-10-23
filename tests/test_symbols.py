import tempfile
import unittest
from pathlib import Path
from gemini_cli.tools.local.symbols import project_map


class SymbolsTests(unittest.TestCase):
    def test_map_cache_unicode_and_changed_file(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root, 'a.py')
            file.write_text('import os\nfrom .b import x\nclass Пример:\n def метод(self): pass\n', encoding='utf-8')
            def run():
                return project_map(root, approve=lambda _: True)['data']['files']
            first = run()
            self.assertEqual(first[0]['imports'], ['os', '.b'])
            self.assertEqual(first[0]['symbols'][1]['line'], 4)
            self.assertEqual(first, run())
            file.write_text('def changed(): pass\n', encoding='utf-8')
            self.assertEqual(run()[0]['symbols'][0]['name'], 'changed')
            file.unlink()
            self.assertEqual(run(), [])

    def test_denial_secrets_links_and_budget(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, '.env.py').write_text('def secret(): pass')
            Path(root, 'ok.py').write_text('def visible(): pass')
            result = project_map(root, approve=lambda _: False)
            self.assertEqual(result['error']['code'], 'denied')
            result = project_map(root, approve=lambda _: True)
            self.assertEqual([r['path'] for r in result['data']['files']], ['ok.py'])
            self.assertTrue(project_map(root, approve=lambda _: True, max_files=0)['truncated'])

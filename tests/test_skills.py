import json
from pathlib import Path
import tempfile
import unittest

from gemini_cli.integrations.skills import catalog, metadata, read_file


class SkillsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skills = self.root / 'skills'
        self.skills.mkdir()
        self.config = self.root / 'skills.json'
        self.config.write_text(json.dumps({'version': 1, 'directories': [str(self.skills)]}))
        self.skill = self.skills / 'review'
        self.skill.mkdir()
        self.text = '---\nname: review\ndescription: >\n  Review code\nmetadata:\n  author: me\n---\nBODY'
        (self.skill / 'SKILL.md').write_text(self.text)

    def test_discovery_only_header_and_explicit_load(self):
        (self.skill / 'SKILL.md').write_bytes(self.text.encode() + b'\xff')
        found, errors = catalog(self.config)
        self.assertFalse(errors)
        self.assertIn('Review code', found['review'].description)
        with self.assertRaises(UnicodeError):
            found['review'].load()
        (self.skill / 'SKILL.md').write_text(self.text)
        self.assertIn('BODY', found['review'].load())

    def test_bad_frontmatter_and_size(self):
        for text in ('plain', '---\nname: review\n---', '---\nname: review\nname: review\ndescription: x\n---',
                     '---\nname: wrong\ndescription: x\n---', '---\nname: review\ndescription: &a x\n---',
                     '---\nname: review\ndescription: !!python/object/apply:os.system [echo]\n---'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                metadata(text, 'review')
        for data in (self.text + 'x' * 65536, '---\n' + 'x' * 8192, self.text.replace('BODY', '\x00')):
            (self.skill / 'SKILL.md').write_text(data)
            with self.assertRaises(ValueError):
                read_file(self.skill, 'SKILL.md', header_only=not '\x00' in data)

    def test_duplicates_are_unavailable(self):
        other = self.root / 'other'
        (other / 'review').mkdir(parents=True)
        (other / 'review' / 'SKILL.md').write_text(self.text)
        self.config.write_text(json.dumps({'version': 1, 'directories': [str(self.skills), str(other)]}))
        found, errors = catalog(self.config)
        self.assertFalse(found)
        self.assertTrue(errors)

    def test_paths_and_links(self):
        for path in ('../skills.json', '/etc/passwd', 'scripts/../../x', '.env', 'C:\\secret', 'x//y', 'evil\x1b.py', 'a\u202eb.py'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                read_file(self.skill, path)
        try:
            (self.skill / 'link').symlink_to(self.config)
        except OSError:
            self.skipTest('Symlinks unavailable')
        with self.assertRaises(ValueError):
            read_file(self.skill, 'link')

    def test_no_project_autodiscovery_or_script_execution(self):
        marker = self.root / 'executed'
        (self.skill / 'run.py').write_text(f'open({str(marker)!r}, "w").close()')
        self.assertEqual(catalog(self.root / 'missing.json'), ({}, []))
        self.assertIn('review', catalog(self.config)[0])
        self.assertFalse(marker.exists())

    def test_portable_documented_examples_validate(self):
        examples = Path(__file__).resolve().parents[1] / 'docs' / 'skills-examples'
        self.config.write_text(json.dumps({'version': 1, 'directories': [str(examples)]}))
        found, errors = catalog(self.config)
        self.assertEqual(set(found), {'task-plan', 'code-review'})
        self.assertFalse(errors)
        for skill in found.values():
            self.assertTrue(skill.load())

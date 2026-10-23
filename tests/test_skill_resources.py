from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from gemini_cli.client.skill_commands import Selection
from gemini_cli.client.skill_resources import read, show, run


class SkillResourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        skill = self.root / 'skills' / 'review'
        (skill / 'scripts').mkdir(parents=True)
        (skill / 'SKILL.md').write_text('---\nname: review\ndescription: review\n---\nReview')
        (skill / 'reference.md').write_text('RESOURCE_ONLY')
        self.script = skill / 'scripts' / 'check.py'
        self.marker = self.root / 'marker'
        self.script.write_text(f'from pathlib import Path\nPath({str(self.marker)!r}).touch()\nprint("SCRIPT_OK")')
        config = self.root / 'skills.json'
        config.write_text(json.dumps({'version': 1, 'directories': [str(self.root / 'skills')]}))
        self.selection = Selection(config)
        self.selection.choose('review')

    def test_only_explicit_resource_loaded_and_scoped(self):
        self.assertNotIn('RESOURCE_ONLY', str(self.selection.payload()))
        show(self.selection, 'reference.md', Mock())
        self.assertNotIn('RESOURCE_ONLY', str(self.selection.payload()))
        read(self.selection, 'reference.md')
        self.assertIn('RESOURCE_ONLY', str(self.selection.payload()))
        self.assertNotIn('SCRIPT_OK', str(self.selection.payload()))
        for path in ('../skills.json', '/etc/passwd', 'scripts/../../x', '.env'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                read(self.selection, path)
        self.selection.bind('new-chat')
        self.assertEqual(self.selection.resources, {})

    def test_view_required_refusal_and_change_during_confirmation(self):
        with self.assertRaises(ValueError):
            run(self.selection, 'scripts/check.py', str(self.root), approve=lambda _: True)
        show(self.selection, 'scripts/check.py', Mock())
        result = run(self.selection, 'scripts/check.py', str(self.root), approve=lambda _: False)
        self.assertIn('отменено пользователем', result)
        def change(_):
            self.script.write_text('print("REPLACED")')
            return True
        result = run(self.selection, 'scripts/check.py', str(self.root), approve=change)
        self.assertIn('error', json.loads(result))
        self.assertFalse(self.marker.exists())

    def test_real_process_snapshot_and_cancellation(self):
        show(self.selection, 'scripts/check.py', Mock())
        result = json.loads(run(self.selection, 'scripts/check.py', str(self.root), approve=lambda _: True))
        self.assertIn('SCRIPT_OK', result['stdout'])
        self.assertTrue(self.marker.exists())
        self.script.write_text('import time\nprint("START", flush=True)\ntime.sleep(30)')
        show(self.selection, 'scripts/check.py', Mock())
        stop = threading.Event()
        timer = threading.Timer(.15, stop.set)
        timer.start()
        try:
            result = json.loads(run(self.selection, 'scripts/check.py', str(self.root),
                                    approve=lambda _: True, cancelled=stop.is_set, monitor=nullcontext))
            self.assertEqual(result['status'], 'cancelled')
        finally:
            timer.join()

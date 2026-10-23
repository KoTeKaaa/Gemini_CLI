import tempfile
import unittest
from pathlib import Path
from gemini_cli.tools.local.test_runner import run_tests


class StructuredTests(unittest.TestCase):
    def test_pass_fail_discovery_and_timeout(self):
        with tempfile.TemporaryDirectory() as root:
            tests = Path(root, 'tests'); tests.mkdir(); (tests / '__init__.py').touch()
            file = tests / 'test_sample.py'
            prefix = 'import unittest\nclass Sample(unittest.TestCase):\n def test_one(self): '
            for body, passed in [('self.assertTrue(True)', True), ('self.fail("успешно")', False),
                                 ('raise RuntimeError("error")', False)]:
                file.write_text(prefix + body + '\n', encoding='utf-8')
                result = run_tests({'modules': ['tests.test_sample']}, root, approve=lambda _: True)
                self.assertEqual(result['data']['passed'], passed)
                self.assertEqual(result['data']['report']['tests_run'], 1)
            file.write_text('invalid python!!!')
            result = run_tests({}, root, approve=lambda _: True)
            self.assertFalse(result['data']['passed'])
            self.assertGreater(result['data']['report']['discovery_errors'], 0)
            file.write_text(prefix + '__import__("time").sleep(5)\n')
            result = run_tests({'timeout': 1}, root, approve=lambda _: True)
            self.assertEqual(result['data']['process_status'], 'timeout')
            self.assertFalse(result['data']['passed'])

    def test_denial_cancel_and_empty_discovery(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'tests').mkdir()
            self.assertFalse(run_tests({}, root, approve=lambda _: True)['data']['passed'])
            self.assertEqual(run_tests({}, root, approve=lambda _: False)['error']['code'], 'denied')
            self.assertEqual(run_tests({}, root, approve=lambda _: True, cancelled=lambda: True)['error']['code'], 'cancelled')
            self.assertEqual(run_tests({'modules': ['--bad']}, root, approve=lambda _: True)['status'], 'error')

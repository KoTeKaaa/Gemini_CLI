import os
import sys
import tempfile
import threading
import unittest
from gemini_cli.client.process import ManagedProcess, ProcessLog


class LogTests(unittest.TestCase):
    def test_bounded_tail(self):
        log = ProcessLog(8)
        log.append("0123456789")
        self.assertTrue(log.truncated)
        self.assertTrue(log.read().endswith("23456789"))


@unittest.skipUnless(os.name == "posix", "POSIX")
class ProcessTests(unittest.TestCase):
    def test_large_logs_and_stderr(self):
        with tempfile.TemporaryDirectory() as cwd:
            process = ManagedProcess([sys.executable, "-c", "import sys; print('x'*200000); print('err',file=sys.stderr)"], cwd)
            try:
                self.assertEqual(process.wait(timeout=4), "completed")
                self.assertLess(len(process.stdout.read()), 66000)
                self.assertIn("err", process.stderr.read())
            finally:
                process.close()

    def test_pty_input_resize_unicode(self):
        process = ManagedProcess([sys.executable, "-c", "print(input(), flush=True)"], ".", pty=True)
        try:
            process.resize(30, 90)
            process.write("Привет\n")
            self.assertEqual(process.wait(timeout=3), "completed")
            self.assertIn("Привет", process.stdout.read())
        finally:
            process.close()

    def test_timeout_and_cancellation_kill_group(self):
        for cancelled, expected in [(lambda: False, "timeout"), (lambda: True, "cancelled")]:
            process = ManagedProcess("sleep 30 & wait", ".")
            self.assertEqual(process.wait(timeout=.1, cancelled=cancelled), expected)
            self.assertIsNotNone(process.poll())
            with self.assertRaises(ProcessLookupError):
                os.killpg(process.process.pid, 0)
            process.close()

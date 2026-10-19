import os
import sys
import time
import unittest
from gemini_cli.client.process_windows import start_process


@unittest.skipUnless(os.name == "nt", "Real Windows ConPTY")
class ConPTYTests(unittest.TestCase):
    def test_input_unicode_resize_and_exit(self):
        process = start_process([sys.executable, "-c", "print(input(),flush=True)"], os.getcwd(), pty=True)
        try:
            process.resize(30, 100)
            process.write("Привет\r\n")
            self.assertEqual(process.wait(timeout=10), "completed")
            self.assertIn("Привет", process.stdout.read())
        finally:
            process.close()

    def test_stop_child_tree(self):
        process = start_process([sys.executable, "-c",
            "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); print(p.pid,flush=True); time.sleep(60)"],
            os.getcwd(), pty=True)
        try:
            deadline = time.monotonic() + 10
            while not any(line.strip().isdigit() for line in process.stdout.read().splitlines()) and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(any(line.strip().isdigit() for line in process.stdout.read().splitlines()))
            self.assertEqual(process.wait(cancelled=lambda: True), "cancelled")
            self.assertIsNotNone(process.poll())
        finally:
            process.close()

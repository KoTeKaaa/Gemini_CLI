import os
import re
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
            "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); print('CHILD_PID='+str(p.pid),flush=True); time.sleep(60)"],
            os.getcwd(), pty=True)
        try:
            deadline = time.monotonic() + 10
            while "CHILD_PID=" not in process.stdout.read() and time.monotonic() < deadline:
                time.sleep(.05)
            output = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", process.stdout.read())
            match = re.search(r"CHILD_PID=(\d+)", output)
            self.assertIsNotNone(match, repr(output[-1000:]))
            from ctypes import wintypes
            api = process.job.api
            api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            api.WaitForSingleObject.restype = wintypes.DWORD
            child = api.OpenProcess(0x100000 | 0x1000, False, int(match.group(1)))
            self.assertTrue(child)
            try:
                self.assertEqual(process.wait(cancelled=lambda: True), "cancelled")
                self.assertEqual(api.WaitForSingleObject(child, 2000), 0, "Child process survived cancellation")
                self.assertIsNotNone(process.poll())
            finally:
                api.CloseHandle(child)
        finally:
            process.close()

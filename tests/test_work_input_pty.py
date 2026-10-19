import os
import sys
import time
import unittest


@unittest.skipUnless(os.name == "posix", "POSIX PTY")
class WorkInputPTYTests(unittest.TestCase):
    def test_escape_alone_f2_and_terminal_restore(self):
        import pty
        import subprocess
        import select
        script = """
import termios
from gemini_cli.client.work_input import WorkInput
from gemini_cli.runtime.turn import TurnState
state = TurnState()
before = termios.tcgetattr(0)
with WorkInput(state, lambda key: print('KEY:' + key, flush=True)):
    print('LISTENING', flush=True)
    assert state.cancelled.wait(3), 'Escape was not dispatched'
assert termios.tcgetattr(0) == before
print('RESTORED', flush=True)
"""
        master, slave = pty.openpty()
        child = subprocess.Popen([sys.executable, "-B", "-c", script], stdin=slave,
                                 stdout=slave, stderr=slave, start_new_session=True)
        os.close(slave)
        output = bytearray()
        def until(marker):
            deadline = time.monotonic() + 5
            while marker not in output:
                if time.monotonic() > deadline:
                    self.fail(output.decode(errors="replace"))
                if select.select([master], [], [], .05)[0]:
                    try:
                        output.extend(os.read(master, 65536))
                    except OSError:
                        self.fail(output.decode(errors="replace"))
        try:
            until(b"LISTENING")
            os.write(master, b"\x1bOQ")
            until(b"KEY:f2")
            os.write(master, b"\x1b")
            until(b"RESTORED")
            self.assertEqual(child.wait(timeout=3), 0)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            os.close(master)

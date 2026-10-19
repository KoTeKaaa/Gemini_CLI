"""Regression for zsh OSC hooks, line editing and native terminal restoration."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "posix" and shutil.which("zsh"), "Linux zsh PTY")
class SessionRelayPTYTests(unittest.TestCase):
    def test_zsh_controls_editing_resize_and_reattach(self):
        import pty
        import select
        import fcntl
        import termios
        import struct
        script = """
import termios
from gemini_cli.client.sessions import SessionManager, attach
before = termios.tcgetattr(0)
manager = SessionManager()
try:
    process = manager.start('probe', '.')
    print('RELAY_READY', flush=True)
    attach(process)
    assert termios.tcgetattr(0) == before
    print('RELAY_DETACHED', flush=True)
    attach(manager.get('probe'))
    assert termios.tcgetattr(0) == before
    print('RELAY_RESTORED', flush=True)
finally:
    manager.close()
"""
        with tempfile.TemporaryDirectory() as home:
            Path(home, ".zshrc").write_text("bindkey -e\nPROMPT=$'%{\\e]2;RELAY_TITLE\\a%}%F{cyan}relay>%f '\n")
            master, slave = pty.openpty()
            def resize(rows, cols):
                fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            resize(25, 100)
            child = subprocess.Popen([sys.executable, "-B", "-c", script], stdin=slave,
                stdout=slave, stderr=slave, start_new_session=True,
                env={**os.environ, "SHELL": shutil.which("zsh"), "HOME": home,
                     "ZDOTDIR": home, "TERM": "xterm"})
            os.close(slave)
            output = bytearray()
            def until(marker):
                deadline = time.monotonic() + 6
                while marker not in output:
                    if time.monotonic() > deadline:
                        self.fail(repr(output[-2000:]))
                    if select.select([master], [], [], .05)[0]:
                        try:
                            output.extend(os.read(master, 65536))
                        except OSError:
                            self.fail(repr(output[-2000:]))
            try:
                until(b"RELAY_READY")
                until(b"relay>")
                os.write(master, b"export RELAY_VAR=kept; cd /; printf 'FIRST_%s\\n' ok\r")
                until(b"FIRST_ok\r\n")
                os.write(master, b"printf 'EDIT_%s\\n' oXk\x1b[D\x7f\r")
                until(b"EDIT_ok\r\n")
                resize(18, 90)
                time.sleep(.1)
                os.write(master, b"printf 'SIZE_'; stty size\r")
                until(b"SIZE_18 90\r\n")
                os.write(master, b"\x1d")
                until(b"RELAY_DETACHED")
                os.write(master, "printf 'REATTACH_%s_%s_Привет\\n' \"$RELAY_VAR\" \"$PWD\"\r".encode())
                until("REATTACH_kept_/_Привет\r\n".encode())
                os.write(master, b"\x1d")
                until(b"RELAY_RESTORED")
                self.assertEqual(child.wait(timeout=3), 0)
                self.assertIn(b"\x1b]2;RELAY_TITLE\x07", output)
                self.assertIn(b"\x1b[?2004h", output)
                self.assertNotIn(b"^M", output)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
                os.close(master)

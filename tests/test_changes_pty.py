"""Реальные POSIX TTY и UI с офлайн backend-фикстурой обоих режимов."""

import os
import sys
import unittest


@unittest.skipUnless(os.name == "posix", "POSIX PTY")
class ChangesPTYTest(unittest.TestCase):
    def test_select_diff_search_resize_undo_in_both_modes(self):
        import fcntl
        from pathlib import Path
        import pty
        import select
        import signal
        import struct
        import subprocess
        import tempfile
        import termios
        import time

        script = '''
import os, termios
import main
from gemini_cli.backends.base import StreamResult
class Backend:
    mode = MODE
    profile = 'fixture'
    base_url = 'https://example.com'
    account_id = 'fixture'
    calls = 0
    def context_info(self, payload): return {}
    def limits(self, model): return {}
    def stream_chat(self, payload):
        self.calls += 1
        if self.calls == 1:
            return StreamResult(events=[{'type': 'tool_call', 'name': 'write_local_files', 'call_id': 'write',
                'args': {'files': [{'filepath': 'one', 'content': 'агент\\r\\n'},
                                   {'filepath': 'two', 'content': 'second\\n'}]}}])
        return StreamResult(events=[{'type': 'text', 'content': 'DONE_S6'}])
main.show_chat_menu = lambda client: (None, True)
main.print_banner = lambda *a: None
os.chdir(WORKSPACE)
before = termios.tcgetattr(0)
main.main(Backend())
assert termios.tcgetattr(0) == before
print('TTY_RESTORED', flush=True)
'''
        for mode in ("local", "remote"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as home:
                root = Path(home) / "workspace"
                root.mkdir()
                (root / "one").write_bytes(b"manual\r\n")
                master, slave = pty.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
                child = subprocess.Popen([sys.executable, "-B", "-c", script.replace("MODE", repr(mode))
                    .replace("WORKSPACE", repr(str(root)))], stdin=slave, stdout=slave, stderr=slave,
                    env={**os.environ, "HOME": home, "TERM": "xterm-256color"}, start_new_session=True)
                os.close(slave)
                output = bytearray()

                def until(marker):
                    deadline = time.monotonic() + 8
                    while marker.encode() not in output:
                        if time.monotonic() > deadline or child.poll() is not None:
                            self.fail(output[-6000:].decode(errors="replace"))
                        if select.select([master], [], [], .05)[0]:
                            data = os.read(master, 65536)
                            output.extend(data)
                            if b"\x1b[6n" in data:
                                os.write(master, b"\x1b[1;1R")

                def send(text):
                    output.clear()
                    os.write(master, text.encode())
                try:
                    until("›")
                    send("change\r")
                    until("Выберите файлы")
                    self.assertNotIn(b"n/p", output)
                    send("\t\r")
                    until("Применение изменений")
                    self.assertNotIn(b"n/p", output)
                    send("\t\r")
                    until("DONE_S6")
                    self.assertNotIn(b"n/p", output)
                    until("/undo")
                    until("›")
                    self.assertEqual((root / "one").read_bytes(), "агент\r\n".encode())
                    self.assertTrue((root / "two").exists())
                    send("/diff\r")
                    until("фактически записано")
                    send("n")
                    until("two")
                    send("/second\r")
                    time.sleep(.1)
                    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 70, 0, 0))
                    child.send_signal(signal.SIGWINCH)
                    send("q")
                    until("›")
                    send("/undo\r")
                    until("Выберите файлы для отката")
                    send(" \t\r")
                    until("Восстановить выбранные файлы")
                    send("\r")
                    until("Восстановлено")
                    until("›")
                    self.assertEqual((root / "one").read_bytes(), b"manual\r\n")
                    self.assertEqual((root / "two").read_bytes(), b"second\n")
                    send("/undo\r")
                    until("Выберите файлы для отката")
                    send(" \t\r")
                    until("Восстановить выбранные файлы")
                    send("\r")
                    until("Восстановлено")
                    until("›")
                    self.assertFalse((root / "two").exists())
                    send("exit\r")
                    until("TTY_RESTORED")
                    self.assertEqual(child.wait(timeout=5), 0)
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait()
                    os.close(master)

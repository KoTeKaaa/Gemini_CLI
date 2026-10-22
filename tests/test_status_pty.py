import os
import sys
import unittest


@unittest.skipUnless(os.name == "posix", "POSIX PTY")
class StatusPTYTests(unittest.TestCase):
    def test_remote_local_unicode_and_resize(self):
        import fcntl
        import pty
        import select
        import signal
        import struct
        import subprocess
        import tempfile
        import termios
        import time

        script = '''
import main
class Backend:
    mode = MODE
    profile = 'fixture'
    base_url = 'https://example.com'
    account_id = 'fixture'
    def get_history(self, chat): return []
    def context_info(self, payload): return {'input_tokens': 10, 'input_token_limit': 100}
    def limits(self, model):
        assert self.mode == 'remote'
        return {'remaining': 12, 'limit': 20}
main.show_chat_menu = lambda client: (None, True)
main.print_banner = lambda *args: None
main.main(Backend())
'''
        for mode in ("remote", "local"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as home:
                master, slave = pty.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 120, 0, 0))
                env = {**os.environ, "HOME": home, "TERM": "xterm-256color"}
                child = subprocess.Popen([sys.executable, "-B", "-c", script.replace("MODE", repr(mode))],
                                         stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True)
                os.close(slave)
                output = bytearray()
                def until(marker):
                    deadline = time.monotonic() + 5
                    while marker not in output:
                        if time.monotonic() > deadline or child.poll() is not None:
                            self.fail(output.decode(errors="replace"))
                        if select.select([master], [], [], .05)[0]:
                            output.extend(os.read(master, 65536))
                            if b"\x1b[6n" in output:
                                os.write(master, b"\x1b[1;1R")
                try:
                    until("Временный".encode())
                    if mode == "remote":
                        until("подписка 12/20".encode())
                    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 40, 0, 0))
                    child.send_signal(signal.SIGWINCH)
                    os.write(master, b"exit\r")
                    self.assertEqual(child.wait(timeout=5), 0)
                    self.assertNotIn(b"Traceback", output)
                    if mode == "local":
                        self.assertNotIn("подписка".encode(), output)
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait()
                    os.close(master)

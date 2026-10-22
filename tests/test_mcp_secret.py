"""Секретный ввод не возвращает ключ в composer/typeahead или историю."""
import os
from pathlib import Path
import sys
import unittest


class MCPSecretTest(unittest.TestCase):
    def test_shared_input_keeps_next_message_and_no_secret_history(self):
        from prompt_toolkit import PromptSession
        from prompt_toolkit.input.defaults import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        from unittest.mock import patch
        from gemini_cli.client.mcp_commands import prompt_secret
        sessions = []
        def create(**kwargs):
            session = PromptSession(**kwargs)
            sessions.append(session)
            return session
        with create_pipe_input() as pipe, patch('prompt_toolkit.PromptSession', side_effect=create):
            chat = PromptSession(input=pipe, output=DummyOutput())
            pipe.send_text('fixture-key\nnext-message\n')
            self.assertEqual(prompt_secret('Key: ', input=chat.input, output=chat.output), 'fixture-key')
            self.assertEqual(chat.prompt('Chat: '), 'next-message')
        self.assertEqual(sessions[0].history.get_strings(), [])
        self.assertEqual(sessions[0].default_buffer.text, '')
        self.assertNotIn('fixture-key', chat.history.get_strings())

    @unittest.skipUnless(os.name == 'posix', 'POSIX PTY')
    def test_mask_typeahead_and_cancellation_in_chat(self):
        import fcntl
        import json
        import pty
        import select
        import struct
        import subprocess
        import tempfile
        import termios
        import time
        script = '''
import main
from gemini_cli.integrations.mcp.manager import Manager
class Backend:
    mode = 'local'
    profile = 'fixture'
    def context_info(self, payload): return {}
    def stream_chat(self, payload): raise AssertionError('secret must never be sent')
def connect(self, name, **kwargs):
    assert self.storage(name).get('bearer') == 'fixture-password'
    print('TOKEN_STORED', flush=True)
Manager.connect = connect
main.show_chat_menu = lambda client: (None, True)
main.print_banner = lambda *args: None
sessions = []
original = main.PromptSession
def tracked(*args, **kwargs):
    session = original(*args, **kwargs)
    sessions.append(session)
    return session
main.PromptSession = tracked
main.main(Backend())
assert all('fixture-password' not in s.history.get_strings() for s in sessions)
print('SECRET_INPUT_CLEAN', flush=True)
'''
        for scenario in ('masked', 'typeahead', 'cancel'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as home:
                config = Path(home) / '.gemini_cli'
                config.mkdir()
                (config / 'mcp.json').write_text(json.dumps({'version': 1, 'servers': [
                    {'name': 'github', 'transport': 'http', 'url': 'https://example.invalid/mcp', 'auth': 'bearer'}]}))
                master, slave = pty.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 120, 0, 0))
                child = subprocess.Popen([sys.executable, '-B', '-c', script],
                    stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                    env={**os.environ, 'HOME': home, 'TERM': 'xterm-256color'})
                os.close(slave)
                output, cursor = bytearray(), 0
                def until(marker):
                    nonlocal cursor
                    deadline = time.monotonic() + 12
                    while True:
                        position = output.find(marker.encode(), cursor)
                        if position >= 0:
                            cursor = position + len(marker.encode())
                            return
                        if time.monotonic() > deadline or child.poll() is not None:
                            self.fail(output[-3000:].decode(errors='replace'))
                        if select.select([master], [], [], .05)[0]:
                            data = os.read(master, 65536)
                            output.extend(data)
                            if b'\x1b[6n' in data:
                                os.write(master, b'\x1b[1;1R')
                try:
                    until('›')
                    if scenario == 'masked':
                        os.write(master, b'/mcp ')
                        until('check')
                        os.write(master, b'login ')
                        until('github')
                        os.write(master, b'github ')
                        until('keyring')
                        os.write(master, b'\x15')
                    os.write(master, b'/mcp login github memory\r' +
                             (b'fixture-password\r' if scenario == 'typeahead' else b''))
                    until('Персональный bearer MCP:')
                    if scenario != 'typeahead':
                        os.write(master, b'fixture-password')
                        until('********')
                        os.write(master, b'\x03' if scenario == 'cancel' else b'\r')
                    until('действие не выполнено' if scenario == 'cancel' else 'действие выполнено')
                    until('›')
                    os.write(master, b'exit\r')
                    until('SECRET_INPUT_CLEAN')
                    self.assertEqual(child.wait(timeout=8), 0)
                    self.assertNotIn(b'fixture-password', output)
                    if scenario == 'cancel':
                        self.assertNotIn(b'TOKEN_STORED', output)
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait()
                    os.close(master)

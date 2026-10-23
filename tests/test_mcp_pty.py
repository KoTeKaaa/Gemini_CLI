"""Настоящий терминал + SDK stdio в обоих режимах, без LLM/внешних credentials."""
import os
from pathlib import Path
import sys
import unittest


@unittest.skipUnless(os.name == 'posix', 'POSIX PTY')
class MCPPTYTest(unittest.TestCase):
    def test_explicit_enable_call_and_disable_both_modes(self):
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
import termios, main
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
            name = next(d['name'] for d in payload['mcp_tools'] if d['description'].startswith(''))
            return StreamResult(events=[{'type': 'tool_call', 'name': name,
                'args': {'text': 'привет'}, 'call_id': 'mcp1', 'thought_signature': 'c2ln'}])
        assert payload['history'][-1]['call_id'] == 'mcp1'
        assert 'привет' in payload['history'][-1]['content']
        return StreamResult(events=[{'type': 'text', 'content': 'DONE_MCP'}])
main.show_chat_menu = lambda client: (None, True)
main.print_banner = lambda *args: None
before = termios.tcgetattr(0)
main.main(Backend())
assert termios.tcgetattr(0) == before
print('TTY_RESTORED', flush=True)
'''
        for mode in ('local', 'remote'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as home:
                config = Path(home) / '.gemini_cli'
                config.mkdir()
                (config / 'mcp.json').write_text(json.dumps({'version': 1, 'servers': [
                    {'name': 'fixture', 'transport': 'stdio', 'command': sys.executable,
                     'args': [str(Path(__file__).with_name('mcp_fixture.py').resolve())]}]}))
                master, slave = pty.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 120, 0, 0))
                child = subprocess.Popen([sys.executable, '-B', '-c', script.replace('MODE', repr(mode))],
                    stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                    env={**os.environ, 'HOME': home, 'TERM': 'xterm-256color'})
                os.close(slave)
                output, cursor = bytearray(), 0
                def until(marker):
                    nonlocal cursor
                    deadline = time.monotonic() + 15
                    while True:
                        position = output.find(marker.encode(), cursor)
                        if position >= 0:
                            cursor = position + len(marker.encode())
                            return
                        if time.monotonic() > deadline or child.poll() is not None:
                            self.fail(output[-4000:].decode(errors='replace'))
                        if select.select([master], [], [], .05)[0]:
                            data = os.read(master, 65536)
                            output.extend(data)
                            if b'\x1b[6n' in data:
                                os.write(master, b'\x1b[1;1R')
                def send(text):
                    nonlocal cursor
                    output.clear()
                    cursor = 0
                    os.write(master, text.encode())
                try:
                    until('›')
                    send('/mcp enable fixture\r')
                    until('действие выполнено')
                    until('›')
                    send('echo\r')
                    until('Разрешить этот MCP-вызов?')
                    send('y\r')
                    until('DONE_MCP')
                    until('›')
                    send('/mcp disable fixture\r')
                    until('действие выполнено')
                    until('›')
                    send('exit\r')
                    until('TTY_RESTORED')
                    self.assertEqual(child.wait(timeout=8), 0)
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait()
                    os.close(master)

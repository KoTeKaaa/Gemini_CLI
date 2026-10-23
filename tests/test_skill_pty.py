"""Реальный POSIX TTY: явный навык/ресурс/скрипт, оба backend без сети и LLM."""
import os
from pathlib import Path
import sys
import unittest


@unittest.skipUnless(os.name == 'posix', 'POSIX PTY')
class SkillPTYTest(unittest.TestCase):
    def test_cli_selection_resource_script_clear_and_terminal_restore(self):
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
            assert 'ONLY_RESOURCE' in payload['skill_context']['content']
            assert 'SCRIPT_BODY' not in payload['skill_context']['content']
            return StreamResult(events=[{'type': 'text', 'content': 'SKILL_ON'}])
        assert 'skill_context' not in payload
        return StreamResult(events=[{'type': 'text', 'content': 'SKILL_OFF'}])
main.show_chat_menu = lambda client: (None, True)
main.print_banner = lambda *args: None
backend = Backend()
before = termios.tcgetattr(0)
main.main(backend)
assert backend.calls == 2
assert termios.tcgetattr(0) == before
print('TTY_RESTORED', flush=True)
'''
        for mode in ('local', 'remote'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as home:
                root = Path(home)
                config = root / '.gemini_cli'
                config.mkdir()
                skill = root / 'skills' / 'review'
                (skill / 'scripts').mkdir(parents=True)
                (skill / 'SKILL.md').write_text('---\nname: review\ndescription: Review\n---\nDo review')
                (skill / 'reference.md').write_text('ONLY_RESOURCE')
                (skill / 'scripts' / 'check.py').write_text('print("SCRIPT_BODY")')
                (skill / 'scripts' / 'slow.py').write_text('import time\ntime.sleep(30) # SLOW_SCRIPT')
                (config / 'skills.json').write_text(json.dumps({'version': 1, 'directories': [str(root / 'skills')]}))
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
                            self.fail(output[-3000:].decode(errors='replace'))
                        if select.select([master], [], [], .05)[0]:
                            try:
                                data = os.read(master, 65536)
                            except OSError:
                                self.fail(output[-3000:].decode(errors='replace'))
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
                    for topic, marker in (('skill', 'SKILLS: С НУЛЯ'), ('mcp', 'MCP: С НУЛЯ')):
                        send(f'/{topic} help\r')
                        until(marker)
                        send('\x1b')
                        until('›')
                    for command, marker in (('/skill use review', 'Выбран навык'),
                                            ('/skill read reference.md', 'Ресурс добавлен')):
                        send(command + '\r')
                        until(marker)
                        until('›')
                    send('/skill show scripts/check.py\r')
                    until('SCRIPT_BODY')
                    send('\x1b')
                    until('Файл просмотрен')
                    until('›')
                    send('/skill run scripts/check.py\r')
                    until('Запустить просмотренный скрипт?')
                    send('n\r')
                    until('Запуск скрипта отменён')
                    until('›')
                    send('/skill run scripts/check.py\r')
                    until('Запустить просмотренный скрипт?')
                    send('y\r')
                    until('Скрипт завершён')
                    until('›')
                    send('/skill output\r')
                    until('SCRIPT_BODY')
                    send('\x1b')
                    until('›')
                    send('/skill show scripts/slow.py\r')
                    until('SLOW_SCRIPT')
                    send('\x1b')
                    until('Файл просмотрен')
                    until('›')
                    send('/skill run scripts/slow.py\r')
                    until('Запустить просмотренный скрипт?')
                    send('y\r')
                    until('Выполнение скрипта')
                    send('\x1b')
                    until('не завершён успешно')
                    until('›')
                    send('task\r')
                    until('SKILL_ON')
                    until('›')
                    send('/clear\r')
                    until('очищены')
                    until('›')
                    send('task\r')
                    until('SKILL_OFF')
                    until('›')
                    send('exit\r')
                    until('TTY_RESTORED')
                    self.assertEqual(child.wait(timeout=8), 0)
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait()
                    os.close(master)

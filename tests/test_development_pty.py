"""Настоящий TTY обоих режимов: справка, tools, Esc LSP и восстановление терминала."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_git_tools import repository
from tests.test_lsp import FIXTURE


@unittest.skipUnless(os.name == 'posix', 'POSIX PTY')
class DevelopmentPTYTests(unittest.TestCase):
    def test_both_modes_tools_help_and_lsp_cancel(self):
        import fcntl
        import pty
        import select
        import struct
        import subprocess
        import termios
        import time
        script = '''
import os,termios,json,main
from gemini_cli.backends.base import StreamResult
os.chdir(ROOT)
class Backend:
 mode=MODE
 profile='fixture'
 base_url='https://example.com'
 account_id='fixture'
 calls=0
 def context_info(self,payload): return {}
 def limits(self,model): return {}
 def stream_chat(self,payload):
  self.calls+=1
  if self.calls==1:
   calls=[('python_symbols',{}),('run_tests',{'modules':['tests.test_one']}),('git_read',{'action':'status','files':['a.py']})]
   return StreamResult(events=[{'type':'tool_call','name':n,'args':a,'call_id':str(i)} for i,(n,a) in enumerate(calls)])
  if self.calls==2:
   results=[json.loads(r['content']) for r in payload['history'] if r['role']=='tool']
   assert len(results)==3 and all(r['status']=='ok' for r in results), results
   return StreamResult(events=[{'type':'text','content':'DEV_TOOLS_OK'}])
  assert self.calls==3
  return StreamResult(events=[{'type':'tool_call','name':'python_lsp','call_id':'slow','args':{'action':'definition','filepath':'a.py','line':1,'character':0}}])
main.show_chat_menu=lambda _: (None,True)
main.print_banner=lambda *args:None
main.confirm_content_scope=lambda _:True
backend=Backend()
before=termios.tcgetattr(0)
main.main(backend)
assert backend.calls==3,backend.calls
assert termios.tcgetattr(0)==before
print('DEV_TTY_RESTORED',flush=True)
'''
        for mode in ('local', 'remote'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as root:
                repository(root)
                tests = Path(root, 'tests'); tests.mkdir(); (tests / '__init__.py').touch()
                (tests / 'test_one.py').write_text('import unittest\nclass One(unittest.TestCase):\n def test_one(self): pass\n')
                server = Path(root, 'fixture-lsp')
                server.write_text('#!' + sys.executable + '\n' + FIXTURE.replace(
                    "if m['method']=='hang': continue", "if m['method']=='textDocument/definition':\n  open('.lsp_wait','w').close();continue"))
                server.chmod(0o755)
                master, slave = pty.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 32, 120, 0, 0))
                child = subprocess.Popen([sys.executable, '-B', '-c', script.replace('ROOT', repr(root)).replace('MODE', repr(mode))],
                    stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                    env={**os.environ, 'HOME': home, 'TERM': 'xterm-256color', 'GEMINI_CLI_PYLSP': str(server)})
                os.close(slave)
                output, cursor = bytearray(), 0
                def until(marker):
                    nonlocal cursor
                    deadline = time.monotonic() + 15
                    while True:
                        position = output.find(marker.encode(), cursor)
                        if position >= 0:
                            cursor = position + len(marker.encode()); return
                        if time.monotonic() > deadline or child.poll() is not None:
                            self.fail(output[-3000:].decode(errors='replace'))
                        if select.select([master], [], [], .05)[0]:
                            try: data = os.read(master, 65536)
                            except OSError: self.fail(output[-3000:].decode(errors='replace'))
                            output.extend(data)
                            if b'\x1b[6n' in data: os.write(master, b'\x1b[1;1R')
                def send(value):
                    nonlocal cursor
                    output.clear(); cursor = 0; os.write(master, value.encode())
                try:
                    until('›'); send('/dev help\r'); until('ИНСТРУМЕНТЫ РАЗРАБОТКИ')
                    send('\x1b'); until('›'); send('tools\r'); until('DEV_TOOLS_OK'); until('›')
                    send('cancel lsp\r')
                    deadline = time.monotonic() + 8
                    while not Path(root, '.lsp_wait').exists() and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue(Path(root, '.lsp_wait').exists())
                    send('\x1b'); until('Ход отменён'); until('›'); send('q\r'); until('DEV_TTY_RESTORED')
                    self.assertEqual(child.wait(timeout=5), 0)
                finally:
                    if child.poll() is None: child.kill(); child.wait(timeout=5)
                    os.close(master)

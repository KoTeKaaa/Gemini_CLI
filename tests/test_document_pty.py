"""Реальный TTY: выбранные документы в обоих режимах, без исходных байтов и с Esc worker."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from tests.test_document_pdf import pdf
from tests.test_document_docx import BODY
from tests.test_document_boundary import package
from tests.test_document_xlsx import workbook


@unittest.skipUnless(os.name == 'posix', 'POSIX PTY')
class DocumentPTYTests(unittest.TestCase):
    def test_local_remote_attachment_help_and_worker_cancel(self):
        import fcntl, pty, select, struct, subprocess, termios, time
        script = '''
import os,json,termios,sys,main
from gemini_cli.backends.base import StreamResult
os.chdir(ROOT)
class Backend:
 mode=MODE
 profile='fixture'
 base_url='https://example.com'
 account_id='fixture'
 calls=0
 def context_info(self,payload):return {}
 def limits(self,model):return {}
 def stream_chat(self,payload):
  self.calls+=1
  if self.calls==1:
   text=payload['message']+str(payload['history'])
   assert all(v in text for v in ('FIRST_SELECTED','Второй','Имя')),text
   assert all(v not in text for v in ('SECOND_UNSELECTED','Первый','PRIVATE','%PDF-')),text
   return StreamResult(events=[{'type':'text','content':'DOCUMENTS_OK'}])
  assert self.calls==2
  from gemini_cli.integrations.documents import client
  real=client.ManagedProcess
  client.ManagedProcess=lambda argv,cwd,**kw:real([sys.executable,'-c',"import pathlib,time;pathlib.Path("+repr(ROOT+'/.doc_wait')+").touch();time.sleep(30)"],cwd,**kw)
  return StreamResult(events=[{'type':'tool_call','name':'read_document','call_id':'slow','args':{'filepath':'a.csv','selection':'cells=A1'}}])
main.show_chat_menu=lambda _: (None,True)
main.print_banner=lambda *args:None
main.confirm_content_scope=lambda _:True
backend=Backend();before=termios.tcgetattr(0)
main.main(backend)
assert backend.calls==2
assert termios.tcgetattr(0)==before
print('DOCUMENT_TTY_RESTORED',flush=True)
'''
        for mode in ('local', 'remote'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as root:
                Path(root, 'a.pdf').write_bytes(pdf())
                Path(root, 'a.docx').write_bytes(package(BODY))
                Path(root, 'a.csv').write_bytes('Имя,значение,PRIVATE\nАня,7,PRIVATE'.encode())
                Path(root, 'a.xlsx').write_bytes(workbook())
                master, slave = pty.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 32, 120, 0, 0))
                child = subprocess.Popen([sys.executable, '-B', '-c', script.replace('ROOT', repr(root)).replace('MODE', repr(mode))],
                    stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                    env={**os.environ, 'HOME': home, 'TERM': 'xterm-256color'})
                os.close(slave)
                output, cursor = bytearray(), 0
                def until(marker):
                    nonlocal cursor
                    deadline = time.monotonic() + 15
                    while True:
                        position = output.find(marker.encode(), cursor)
                        if position >= 0: cursor = position + len(marker.encode()); return
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
                    until('›'); send('/doc help\r'); until('ДОКУМЕНТЫ: ВЫБОР ДИАПАЗОНА')
                    send('\x1b'); until('›')
                    for selection in ('@a.pdf#pages=1', '@a.docx#paragraphs=2', '@a.csv#cells=A1:B1', '@a.xlsx#sheet=Данные&cells=A1:B1'):
                        send(selection+'\r'); until('Добавлено'); until('›')
                    send('read selected\r'); until('DOCUMENTS_OK'); until('›')
                    send('cancel worker\r')
                    deadline = time.monotonic() + 8
                    while not Path(root, '.doc_wait').exists() and time.monotonic() < deadline: time.sleep(.02)
                    self.assertTrue(Path(root, '.doc_wait').exists())
                    send('\x1b'); until('Ход отменён'); until('›'); send('q\r'); until('DOCUMENT_TTY_RESTORED')
                    self.assertEqual(child.wait(timeout=5), 0)
                finally:
                    if child.poll() is None: child.kill(); child.wait(timeout=5)
                    os.close(master)

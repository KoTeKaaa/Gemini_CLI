import json
import sys
import tempfile
import unittest
from pathlib import Path
from gemini_cli.integrations.lsp import LSPClient

FIXTURE = '''import json,sys
while True:
 h=sys.stdin.buffer.readline()
 if not h: break
 n=int(h.split(b':')[1]);sys.stdin.buffer.readline()
 m=json.loads(sys.stdin.buffer.read(n))
 if 'id' not in m: continue
 if m['method']=='hang': continue
 r={'jsonrpc':'2.0','id':m['id'],'result':{'capabilities':{}}}
 if m['method']=='bad': r={'jsonrpc':'2.0','id':m['id'],'error':{'code':1}}
 b=json.dumps(r).encode();sys.stdout.buffer.write(b'Content-Length: '+str(len(b)).encode()+b'\\r\\n\\r\\n'+b);sys.stdout.buffer.flush()
'''


class LSPTests(unittest.TestCase):
    def test_process_requests_error_timeout_and_shutdown(self):
        with tempfile.TemporaryDirectory() as root:
            script = Path(root, 'fixture.py'); script.write_text(FIXTURE)
            client = LSPClient([sys.executable, str(script)], root, timeout=.4)
            try:
                client.initialize()
                client.open_document(script, FIXTURE)
                with self.assertRaises(ValueError): client.open_document(script, FIXTURE)
                with self.assertRaises(ValueError): client.request('bad')
                with self.assertRaises(TimeoutError): client.request('hang')
                self.assertGreater(client.sequence, 2)
            finally:
                client.close()
            self.assertIsNotNone(client.process.poll())

    def test_missing_server_and_cancel(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(OSError): LSPClient(['missing-lsp-executable-12345'], root)
            client = LSPClient([sys.executable, '-c', 'import time;time.sleep(5)'], root,
                               cancelled=lambda: True)
            try:
                with self.assertRaises(InterruptedError): client.request('test')
            finally: client.close()

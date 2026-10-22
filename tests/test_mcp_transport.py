from pathlib import Path
import sys
import threading
import unittest

from gemini_cli.integrations.mcp.config import Connection
from gemini_cli.integrations.mcp.transport import Session, MCPUnavailable


class MCPTransportTest(unittest.TestCase):
    def connection(self, **kwargs):
        return Connection('fixture', 'stdio', command=sys.executable,
                          args=(str(Path(__file__).with_name('mcp_fixture.py').resolve()),), **kwargs)

    def test_discovery_call_and_shutdown(self):
        session = Session(self.connection())
        try:
            names = [tool['name'] for tool in session.request('list')['tools']]
            self.assertIn('echo', names)
            self.assertIn('hello', session.request('call', 'echo', {'text': 'hello'}))
            self.assertLess(len(session.request('call', 'echo', {'text': 'x' * 40000})), 8192)
        finally:
            session.close()
        self.assertFalse(session.thread.is_alive())

    def test_cancellation_and_timeout_are_bounded(self):
        session = Session(self.connection(timeout=2))
        try:
            cancelled = threading.Event()
            timer = threading.Timer(.15, cancelled.set)
            timer.start()
            with self.assertRaises(MCPUnavailable):
                session.request('call', 'wait', {'seconds': 30}, cancelled=cancelled.is_set)
            timer.join()
            with self.assertRaises(MCPUnavailable):
                session.request('call', 'wait', {'seconds': 30})
        finally:
            session.close()

    def test_handshake_timeout_terminates_child(self):
        import time
        started = time.monotonic()
        with self.assertRaises(MCPUnavailable):
            Session(Connection('hung', 'stdio', command=sys.executable,
                args=('-c', 'import time; time.sleep(30)'), timeout=1))
        self.assertLess(time.monotonic() - started, 9)

    def test_embedded_text_and_media_are_filtered(self):
        import json
        from types import SimpleNamespace as N
        from gemini_cli.integrations.mcp.transport import text_result
        value = N(content=[N(type='resource', resource=N(text='embedded text')),
                           N(type='image', data='PRIVATE-BASE64')], is_error=False)
        result = text_result(value)
        self.assertIn('embedded text', result)
        self.assertNotIn('PRIVATE-BASE64', result)
        self.assertTrue(json.loads(result)['unsupported_media'])

    def test_missing_runtime_safe_error(self):
        with self.assertRaisesRegex(MCPUnavailable, 'runtime'):
            Session(Connection('missing', 'stdio', command='/missing/mcp-runtime', timeout=1))

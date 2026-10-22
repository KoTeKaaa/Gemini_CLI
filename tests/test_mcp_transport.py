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

    def test_missing_runtime_safe_error(self):
        with self.assertRaisesRegex(MCPUnavailable, 'runtime'):
            Session(Connection('missing', 'stdio', command='/missing/mcp-runtime', timeout=1))

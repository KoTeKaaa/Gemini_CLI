import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import requests
from gemini_cli.backends.base import StreamResult
from gemini_cli.backends.cancellation import open_stream
from gemini_cli.backends.remote import decode_sse, interrupt_http
from gemini_cli.runtime.turn import TurnState


class SocketCancelTest(unittest.TestCase):
    def test_cancel_disconnects_server_and_releases_worker(self):
        entered, disconnected = threading.Event(), threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                self.wfile.flush()
                self.connection.settimeout(3)
                entered.set()
                if self.connection.recv(1) == b'':
                    disconnected.set()
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        class Backend:
            def stream_chat(self, payload):
                response = requests.get(f'http://127.0.0.1:{server.server_port}',
                                        stream=True, timeout=5)
                return StreamResult(events=decode_sse(response), on_close=response.close,
                                    on_cancel=lambda: interrupt_http(response))
        backend, state = Backend(), TurnState()
        try:
            response = open_stream(backend, {}, state)
            self.assertTrue(entered.wait(1))
            time.sleep(.05)
            state.cancel()
            self.assertEqual(list(response.events), [])
            self.assertTrue(disconnected.wait(1))
            deadline = time.monotonic() + 1
            while backend._stream_lock.locked() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(backend._stream_lock.locked())
        finally:
            state.cancel()
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()

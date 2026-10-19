import threading
import time
import unittest
from gemini_cli.backends.base import StreamResult
from gemini_cli.backends.cancellation import open_stream
from gemini_cli.runtime.turn import TurnState


class CancelTests(unittest.TestCase):
    def test_slow_open_returns_on_cancel_and_closes_late_response(self):
        gate, closed, entered = threading.Event(), threading.Event(), threading.Event()
        class Backend:
            def stream_chat(self, payload):
                entered.set()
                gate.wait(2)
                return StreamResult(on_close=closed.set)
        backend, state = Backend(), TurnState()
        timer = threading.Timer(.1, state.cancel)
        timer.start()
        start = time.monotonic()
        try:
            with self.assertRaises(InterruptedError):
                open_stream(backend, {}, state)
            self.assertLess(time.monotonic() - start, 1)
            self.assertTrue(entered.is_set())
        finally:
            gate.set()
            timer.join()
        self.assertTrue(closed.wait(1))

    def test_stream_cancel_drops_late_tools_and_releases_slot(self):
        gate, closed = threading.Event(), threading.Event()
        def events():
            yield {"type": "text", "content": "partial"}
            gate.wait(2)
            yield {"type": "tool_call", "name": "execute_command", "args": {}}
        class Backend:
            def stream_chat(self, payload):
                return StreamResult(events=events(), on_close=closed.set)
        backend, state = Backend(), TurnState()
        response = open_stream(backend, {}, state)
        self.assertEqual(next(response.events)["content"], "partial")
        state.cancel()
        self.assertEqual(list(response.events), [])
        gate.set()
        self.assertTrue(closed.wait(1))

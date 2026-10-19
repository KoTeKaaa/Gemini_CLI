"""Thread-safe identity and cancellation shared by UI, streams and tools."""

from threading import Event, RLock
from collections import deque
from uuid import uuid4


class TurnState:
    def __init__(self):
        self.turn_id = str(uuid4())
        self.request_id = None
        self.status = "running"
        self.cancelled = Event()
        self._lock = RLock()
        self._sequence = -1
        self.events = deque(maxlen=64)
        self._callbacks = set()

    def record(self, event):
        # Only status metadata; no arguments, tool output or provider content.
        with self._lock:
            self.events.append({**event, "turn_id": self.turn_id,
                                "request_id": self.request_id})

    def steps(self):
        with self._lock:
            result = {}
            for event in self.events:
                if event.get("type") == "step":
                    result[event["step_id"]] = event.copy()
            return list(result.values())[-8:]

    def request(self, payload):
        with self._lock:
            if self.status != "running":
                raise InterruptedError("Ход остановлен")
            self.request_id = str(uuid4())
            self._sequence = -1
            return {**payload, "turn_id": self.turn_id, "request_id": self.request_id}

    def accepts(self, event):
        with self._lock:
            if self.status != "running":
                return False
            if event.get("turn_id", self.turn_id) != self.turn_id:
                return False
            if event.get("request_id", self.request_id) != self.request_id:
                return False
            sequence = event.get("sequence")
            if sequence is not None:
                if not isinstance(sequence, int) or sequence <= self._sequence:
                    return False
                self._sequence = sequence
            return True

    def on_cancel(self, callback):
        with self._lock:
            self._callbacks.add(callback)
            cancelled = self.cancelled.is_set()
        if cancelled:
            callback()
        def unregister():
            with self._lock:
                self._callbacks.discard(callback)
        return unregister

    def cancel(self):
        with self._lock:
            if self.status != "running":
                return
            self.status = "cancelled"
            self.cancelled.set()
            callbacks = list(self._callbacks)
        for callback in callbacks:
            callback()

    def finish(self, status="completed"):
        with self._lock:
            if self.status == "running":
                self.status = status

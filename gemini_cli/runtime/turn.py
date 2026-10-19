"""Thread-safe identity and cancellation shared by UI, streams and tools."""

from threading import Event, RLock
from uuid import uuid4


class TurnState:
    def __init__(self):
        self.turn_id = str(uuid4())
        self.request_id = None
        self.status = "running"
        self.cancelled = Event()
        self._lock = RLock()
        self._sequence = -1

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

    def cancel(self):
        with self._lock:
            if self.status == "running":
                self.status = "cancelled"
                self.cancelled.set()

    def finish(self, status="completed"):
        with self._lock:
            if self.status == "running":
                self.status = status

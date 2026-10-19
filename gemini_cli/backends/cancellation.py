"""Bounded producer: cancellation returns control even during HTTP/provider waits.

An in-flight provider call may finish later and may still consume quota. The
worker retains its slot until it closes the source; it never writes UI/history.
"""
from queue import Queue, Empty, Full
from threading import Thread, Lock, Event
from .base import StreamResult


def open_stream(backend, payload, state):
    lock = getattr(backend, "_stream_lock", None)
    if lock is None:
        backend._stream_lock = lock = Lock()
    if not lock.acquire(blocking=False):
        return StreamResult(409, detail="Предыдущий поток ещё закрывается; повторите позже")
    ready, events = Queue(1), Queue(1)
    class StopToken:
        def __init__(self):
            self.local = Event()
        def is_set(self):
            return self.local.is_set() or state.cancelled.is_set()
        def set(self):
            self.local.set()
    stopped = StopToken()
    def put(queue, value):
        while not stopped.is_set():
            try:
                queue.put(value, timeout=.05)
                return
            except Full:
                pass
    def produce():
        response = None
        unregister = lambda: None
        try:
            if stopped.is_set():
                return
            cancellable = getattr(type(backend), "stream_chat_cancellable", None)
            response = (cancellable(backend, payload, stopped) if callable(cancellable)
                        else backend.stream_chat(payload))
            interrupt = getattr(response, "on_cancel", lambda: None)
            unregister = state.on_cancel(lambda: Thread(target=interrupt, daemon=True).start())
            put(ready, response)
            if response.status_code == 200:
                from .remote import events_from_response
                source = events_from_response(response) if (isinstance(response, StreamResult)
                         or hasattr(response, "iter_lines")) else ()
                for event in source:
                    if stopped.is_set():
                        break
                    put(events, event)
        except Exception:
            put(ready, StreamResult(502, detail="Поток прерван"))
            put(events, {"type": "error", "content": "Поток прерван"})
        finally:
            unregister()
            try:
                if response is not None:
                    close = getattr(response, "close", None)
                    if close:
                        close()
            finally:
                put(events, None)
                lock.release()
    Thread(target=produce, daemon=True).start()
    def wait(queue):
        while not stopped.is_set():
            try:
                return queue.get(timeout=.05)
            except Empty:
                pass
        raise InterruptedError("Ход отменён")
    response = wait(ready)
    def generate():
        try:
            while not stopped.is_set():
                event = wait(events)
                if event is None:
                    break
                yield event
        except InterruptedError:
            return
    return StreamResult(response.status_code, generate(), getattr(response, "detail", ""),
                        on_close=stopped.set)


def run_cancellable(operation, state):
    result = Queue(1)
    def run():
        try:
            result.put((True, operation()))
        except Exception as error:
            result.put((False, error))
    if state.cancelled.is_set():
        raise InterruptedError("Ход отменён")
    Thread(target=run, daemon=True).start()
    while not state.cancelled.is_set():
        try:
            ok, value = result.get(timeout=.05)
        except Empty:
            continue
        if ok:
            return value
        raise value
    raise InterruptedError("Ход отменён")

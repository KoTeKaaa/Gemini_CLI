"""Listen only during agent work; approvals and /term retain their own input."""
import asyncio
from contextlib import closing
import sys
import threading


class WorkInput:
    def __init__(self, state, on_key=None):
        self.state, self.on_key = state, on_key
        self.loop = self.done = self.worker = None
        self.ready = threading.Event()
        self.error = None

    def handle(self, key):
        if key == "escape":
            self.state.cancel()
        elif self.on_key:
            self.on_key(key)

    def __enter__(self):
        if self.state is None or not sys.stdin.isatty():
            return self
        def run():
            try:
                asyncio.run(self.listen())
            except Exception as error:
                self.error = error
            finally:
                self.ready.set()
        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()
        if not self.ready.wait(1):
            raise RuntimeError("Не удалось запустить чтение Esc/F2")
        if self.error is not None:
            raise RuntimeError("Не удалось запустить чтение Esc/F2") from self.error
        return self

    async def listen(self):
        from prompt_toolkit.input import create_input
        self.loop = asyncio.get_running_loop()
        self.done = asyncio.Event()
        with closing(create_input()) as source:
            flush_handle = None
            def dispatch(presses):
                for press in presses:
                    self.handle(press.key.value if hasattr(press.key, "value") else press.key)
            def flush():
                dispatch(source.flush_keys())
            def read():
                nonlocal flush_handle
                dispatch(source.read_keys())
                if flush_handle:
                    flush_handle.cancel()
                flush_handle = self.loop.call_later(.05, flush)
            with source.raw_mode(), source.attach(read):
                self.ready.set()
                await self.done.wait()

    def __exit__(self, *_):
        if self.loop is not None and self.done is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.done.set)
        if self.worker:
            self.worker.join(2)

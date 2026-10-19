"""Listen only during agent work; approvals and /term retain their own input."""
import asyncio
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
            except (OSError, EOFError, RuntimeError) as error:
                self.error = error
            finally:
                self.ready.set()
        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()
        self.ready.wait(1)
        return self

    async def listen(self):
        from prompt_toolkit.input import create_input
        self.loop = asyncio.get_running_loop()
        self.done = asyncio.Event()
        with create_input() as source:
            def read():
                for press in source.read_keys():
                    self.handle(press.key.value if hasattr(press.key, "value") else press.key)
            with source.raw_mode(), source.attach(read):
                self.ready.set()
                await self.done.wait()

    def __exit__(self, *_):
        if self.loop is not None and self.done is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.done.set)
        if self.worker:
            self.worker.join(2)

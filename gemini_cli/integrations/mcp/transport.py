"""Одна SDK-сессия на подключение; её контексты закрываются в том же task."""

import asyncio
from concurrent.futures import Future, TimeoutError as FutureTimeout
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
from queue import Queue
import threading

from ...runtime.history import bounded_tool_result

MAX_DISCOVERY_BYTES = 65536


class MCPUnavailable(RuntimeError):
    pass


class Session:
    def __init__(self, connection, *, secrets=None, http_factory=None, oauth=None):
        self.connection, self.secrets = connection, secrets or {}
        self.http_factory, self.oauth = http_factory, oauth
        self.queue, self.ready = Queue(), Future()
        self.closed = False
        self.thread = threading.Thread(target=self._run, name="mcp-session", daemon=True)
        self.thread.start()
        try:
            self.ready.result(timeout=connection.timeout + 5)
        except Exception:
            self.close()
            raise MCPUnavailable("MCP: не удалось подключиться; проверьте runtime и /mcp check") from None

    def _run(self):
        try:
            asyncio.run(self._serve())
        except BaseException:
            if not self.ready.done():
                self.ready.set_exception(MCPUnavailable("MCP: подключение недоступно"))
        finally:
            self.closed = True
            while not self.queue.empty():
                item = self.queue.get_nowait()
                if item and not item[2].done():
                    item[2].set_exception(MCPUnavailable("MCP: соединение закрыто"))

    async def _transport(self, stack):
        from mcp.client.stdio import stdio_client, StdioServerParameters
        c = self.connection
        if c.transport == "stdio":
            stderr = stack.enter_context(open(os.devnull, "w"))
            env = {key: self.secrets[key] for key in c.env_keys if key in self.secrets}
            return await stack.enter_async_context(stdio_client(StdioServerParameters(
                command=c.command, args=list(c.args), env=env,
                cwd=str(Path.home())), errlog=stderr))
        return await self._http_transport(stack)

    async def _http_transport(self, stack):
        raise MCPUnavailable("MCP HTTP: транспорт недоступен")

    async def _serve(self):
        import anyio
        from mcp import Client
        async with AsyncExitStack() as stack:
            transport = await self._transport(stack)
            client = await stack.enter_async_context(Client(
                _open_transport(transport), read_timeout_seconds=self.connection.timeout))
            self.ready.set_result(True)
            while True:
                item = await asyncio.to_thread(self.queue.get)
                if item is None:
                    break
                operation, args, future, cancelled = item
                try:
                    with anyio.fail_after(self.connection.timeout):
                        async with anyio.create_task_group() as group:
                            async def watch_cancel(scope):
                                while not cancelled():
                                    await anyio.sleep(.05)
                                scope.cancel()
                            with anyio.CancelScope() as scope:
                                group.start_soon(watch_cancel, scope)
                                if operation == "list":
                                    value = await client.list_tools(cache_mode="refresh")
                                    raw = value.model_dump_json(by_alias=True)
                                    if len(raw.encode()) > MAX_DISCOVERY_BYTES or value.next_cursor:
                                        raise ValueError("Каталог MCP превышает лимит")
                                    result = json.loads(raw)
                                else:
                                    value = await client.call_tool(args[0], args[1])
                                    raw = value.model_dump_json(by_alias=True)
                                    result = bounded_tool_result(raw)
                                group.cancel_scope.cancel()
                            group.cancel_scope.cancel()
                            if scope.cancel_called:
                                raise MCPUnavailable("MCP: вызов отменён")
                    future.set_result(result)
                except Exception:
                    future.set_exception(MCPUnavailable("MCP: вызов не выполнен (отмена, timeout или отказ сервиса)"))

    def request(self, operation, *args, cancelled=lambda: False):
        if self.closed or cancelled():
            raise MCPUnavailable("MCP: соединение закрыто или ход отменён")
        future = Future()
        self.queue.put((operation, args, future, cancelled))
        try:
            return future.result(timeout=self.connection.timeout + 5)
        except FutureTimeout:
            self.close()
            raise MCPUnavailable("MCP: превышено время ожидания") from None

    def close(self):
        self.queue.put(None)
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=self.connection.timeout + 6)
        self.closed = True


from contextlib import asynccontextmanager


@asynccontextmanager
async def _open_transport(streams):
    yield streams

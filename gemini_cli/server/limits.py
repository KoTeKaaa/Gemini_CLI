"""Ограничения HTTP и ограниченный поток с освобождением слота при отключении."""

import json
import time
from queue import Queue, Empty, Full
from threading import Event, Lock, Thread

from fastapi import HTTPException
from starlette.responses import JSONResponse, StreamingResponse


class BodyLimit:
    def __init__(self, app, max_bytes=524288):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.max_bytes:
                return await JSONResponse({"detail": "Запрос слишком велик"}, 413)(scope, receive, send)
            chunks.append(message)
            if not message.get("more_body"):
                break
        async def buffered_receive():
            return chunks.pop(0) if chunks else await receive()
        await self.app(scope, buffered_receive, send)


class GenerationSlots:
    def __init__(self, total=4):
        self.total, self.active, self.lock = total, {}, Lock()

    def acquire(self, user_id: str, limit: int):
        with self.lock:
            if sum(self.active.values()) >= self.total or self.active.get(user_id, 0) >= limit:
                raise HTTPException(429, "Достигнут предел параллельных запросов")
            self.active[user_id] = self.active.get(user_id, 0) + 1

    def release(self, user_id: str):
        with self.lock:
            remaining = self.active[user_id] - 1
            if remaining:
                self.active[user_id] = remaining
            else:
                del self.active[user_id]


SLOTS = GenerationSlots()


class StreamJob:
    def __init__(self, source, user_id, limit, *, slots=SLOTS, timeout=90):
        self.source, self.user_id, self.limit = source, user_id, limit
        self.slots, self.timeout = slots, timeout
        self.cancelled, self.queue = Event(), Queue(maxsize=1)

    def put(self, value):
        while not self.cancelled.is_set():
            try:
                self.queue.put(value, timeout=.1)
                return
            except Full:
                pass

    def produce(self):
        acquired = False
        try:
            self.slots.acquire(self.user_id, self.limit)
            acquired = True
            deadline = time.monotonic() + self.timeout
            for chunk in self.source:
                if self.cancelled.is_set():
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError()
                self.put(chunk)
        except Exception:
            self.put(('data: ' + json.dumps({"type": "error", "content":
                     "Запрос ограничен или прерван"}, ensure_ascii=False) + '\n\n').encode())
        finally:
            try:
                self.source.close()
            finally:
                if acquired:
                    self.slots.release(self.user_id)
                self.put(None)

    def __iter__(self):
        worker = Thread(target=self.produce, daemon=True)
        worker.start()
        try:
            while not self.cancelled.is_set():
                try:
                    chunk = self.queue.get(timeout=.1)
                except Empty:
                    continue
                if chunk is None:
                    break
                yield chunk
        finally:
            self.cancelled.set()


class BoundedStreamingResponse(StreamingResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.job.cancelled.set()

    def __init__(self, job, **kwargs):
        self.job = job
        super().__init__(job, **kwargs)

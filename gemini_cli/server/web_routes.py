"""Авторизованные веб-маршруты; сетевые операции выполняются в worker thread."""

import time
from collections import deque
from threading import Lock

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ..tools.results import failure
from ..tools.web.search import search
from ..tools.web.extract import read_url
from ..tools.web.settings import SEARCH_PER_MINUTE, READ_PER_MINUTE


class SearchPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    max_results: int = Field(default=5, ge=1, le=5, strict=True)


class UserRateLimit:
    def __init__(self, limit: int):
        self.limit = limit
        self.calls = {}
        self.lock = Lock()

    def allow(self, user_id: str) -> bool:
        with self.lock:
            now = time.monotonic()
            self.calls = {key: values for key, values in self.calls.items()
                          if values and values[-1] > now - 60}
            if user_id not in self.calls and len(self.calls) >= 10000:
                return False
            values = self.calls.setdefault(user_id, deque())
            while values and values[0] <= now - 60:
                values.popleft()
            if len(values) >= self.limit:
                return False
            values.append(now)
            return True


class ReadPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)


def create_web_router(get_user, *, api_key=None, search_adapter=search, search_limit=SEARCH_PER_MINUTE,
                      read_adapter=read_url, read_limit=READ_PER_MINUTE):
    router = APIRouter(prefix="/tools/web")
    limiter = UserRateLimit(search_limit)
    read_limiter = UserRateLimit(read_limit)

    @router.post("/read")
    def web_read(payload: ReadPayload, user=Depends(get_user)):
        if not read_limiter.allow(user.user_id):
            return failure("rate_limit", "Достигнут минутный лимит чтения URL")
        try:
            return read_adapter(payload.url)
        except Exception:
            return failure("fetch_failed", "Не удалось прочитать URL")

    @router.post("/search")
    def web_search(payload: SearchPayload, user=Depends(get_user)):
        if not payload.query.strip():
            return failure("invalid_arguments", "Поисковый запрос пуст")
        if not api_key:
            return failure("unavailable", "Веб-поиск не настроен на сервере")
        if not limiter.allow(user.user_id):
            return failure("rate_limit", "Достигнут минутный лимит поиска")
        try:
            return search_adapter(payload.query, payload.max_results, api_key=api_key)
        except Exception:
            return failure("provider_error", "Сервис поиска временно недоступен")

    return router

"""Ограниченный кэш одного провайдерского проекта/профиля."""

from copy import deepcopy
from threading import Lock
import time

from ..protocol.quotas import unavailable
from ..tools.web.usage import tavily_usage


class QuotaService:
    minimum_refresh_seconds = 300

    def __init__(self, scope: str, tavily_key=None, *, fetch=tavily_usage,
                 clock=time.monotonic, wall=time.time):
        self.scope, self.key, self.fetch = scope, tavily_key, fetch
        self.clock, self.wall = clock, wall
        self.lock = Lock()
        self.next_fetch, self.rows = float("-inf"), []

    def get(self, model: str, *, refresh=False) -> dict:
        # Explicit refresh also observes the minimum interval. A failed read
        # consumes this interval, preventing request storms from two clients.
        with self.lock:
            now = self.clock()
            if now >= self.next_fetch:
                self.next_fetch = now + self.minimum_refresh_seconds
                try:
                    rows = self.fetch(self.key, self.scope)
                except Exception:
                    rows = [unavailable("tavily", self.scope, "provider_unavailable",
                                        fetched_at=self.wall())]
                if self.rows and all(row.get("unavailable") for row in rows):
                    self.rows = [{**row, "stale": True, "reason": rows[0].get("reason")}
                                 for row in self.rows]
                else:
                    self.rows = rows
            result = deepcopy(self.rows)
            result.insert(0, unavailable("gemini", self.scope, "monitoring_not_configured", model=model))
            return {"quotas": result, "minimum_refresh_seconds": self.minimum_refresh_seconds}

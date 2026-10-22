"""Снимки провайдерских квот; бюджет подписки сюда не входит."""

from dataclasses import asdict, dataclass
import math


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


@dataclass(frozen=True)
class Quota:
    provider: str
    scope: str
    model: str | None = None
    tier: str | None = None
    unit: str = "requests"
    window: str | None = None
    limit: float | None = None
    used: float | None = None
    sampled_at: float | None = None
    fetched_at: float | None = None
    reset_at: float | None = None
    unavailable: bool = False
    stale: bool = False
    approximate: bool = False
    reason: str | None = None

    def __post_init__(self):
        for key in ("limit", "used", "sampled_at", "fetched_at", "reset_at"):
            object.__setattr__(self, key, number(getattr(self, key)))

    @property
    def remaining(self):
        if self.unavailable or self.limit is None or self.used is None:
            return None
        return max(0, self.limit - self.used)

    def wire(self) -> dict:
        return {**asdict(self), "remaining": self.remaining}


def unavailable(provider: str, scope: str, reason: str, *, model=None, fetched_at=None) -> dict:
    return Quota(provider, scope, model=model, unavailable=True,
                 reason=reason, fetched_at=fetched_at).wire()

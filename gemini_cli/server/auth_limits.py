"""Ограничение попыток; IP используется только как сигнал злоупотребления."""

import hashlib
import time
from collections import deque
from threading import Lock

from fastapi import HTTPException


class AuthLimits:
    def __init__(self, *, clock=time.monotonic, window=60):
        self.clock, self.window, self.calls, self.lock = clock, window, {}, Lock()

    def check(self, request, action: str, identity: str, limit=12):
        # Request.client is populated by the explicitly trusted ASGI proxy config.
        # Never read user-supplied forwarding headers here.
        source = request.client.host if request.client else "unknown"
        digest = hashlib.sha256(identity.encode()).hexdigest()
        keys = (("global", 300), ((action, source), max(40, limit)),
                ((action, digest, source), limit))
        with self.lock:
            now = self.clock()
            self.calls = {key: values for key, values in self.calls.items()
                          if values and values[-1] > now - self.window}
            if len(self.calls) >= 10000:
                raise HTTPException(429, "Слишком много попыток. Повторите позже.")
            for key, maximum in keys:
                values = self.calls.setdefault(key, deque())
                while values and values[0] <= now - self.window:
                    values.popleft()
                if len(values) >= maximum:
                    raise HTTPException(429, "Слишком много попыток. Повторите позже.")
            for key, _ in keys:
                self.calls[key].append(now)


AUTH_LIMITS = AuthLimits()

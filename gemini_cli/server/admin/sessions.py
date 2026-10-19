"""Подписанный cookie содержит только случайный ID; токены остаются в RAM сервера."""

import os
import secrets
import time
from threading import Lock
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from ..auth_limits import AUTH_LIMITS


def require_owner(user):
    owner = os.getenv("ADMIN_USER_ID", "")
    if not owner:
        raise HTTPException(503, "Владелец панели не настроен")
    if user.user_id != owner:
        raise HTTPException(403, "Доступен только владельцу панели")
    return user


def owner_dependency(get_user):
    def owner(user=Depends(get_user)):
        return require_owner(user)
    return owner


class WebLogin(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)
    csrf: str = Field(min_length=32, max_length=128)


class WebSessions:
    def __init__(self, authenticate, *, ttl=1800):
        self.authenticate, self.ttl = authenticate, ttl
        self.entries, self.lock = {}, Lock()

    def check_origin(self, request: Request):
        origin = os.getenv("ADMIN_ORIGIN", "")
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment
                or len(os.getenv("ADMIN_SESSION_SECRET", "")) < 32):
            raise HTTPException(503, "Веб-панель не настроена")
        if request.headers.get("origin") != origin:
            raise HTTPException(403, "Недоверенный источник запроса")

    def check_csrf(self, request: Request, token: str | None = None):
        self.check_origin(request)
        token = token or request.headers.get("x-csrf-token", "")
        expected = request.session.get("csrf", "")
        if not expected or not secrets.compare_digest(token, expected):
            raise HTTPException(403, "Недействительная CSRF-защита")
        AUTH_LIMITS.check(request, "web_write", request.session.get("sid", expected), 40)

    def create(self, request, token, user):
        now = time.monotonic()
        with self.lock:
            self.entries = {key: entry for key, entry in self.entries.items() if entry[2] > now}
            self.entries.pop(request.session.get("sid"), None)
            if len(self.entries) >= 4096:
                raise HTTPException(503, "Веб-сессии временно недоступны")
            sid = secrets.token_urlsafe(32)
            self.entries[sid] = (token, user.user_id, now + self.ttl)
        request.session.clear()
        request.session.update(sid=sid, csrf=secrets.token_urlsafe(32))

    def current_user(self, request: Request):
        AUTH_LIMITS.check(request, "web_session", request.session.get("sid", "anonymous"), 90)
        with self.lock:
            entry = self.entries.get(request.session.get("sid"))
        if not entry or entry[2] <= time.monotonic():
            self.logout(request)
            raise HTTPException(401, "Войдите в веб-панель")
        try:
            user = self.authenticate("Bearer " + entry[0])
            if user.user_id != entry[1]:
                raise HTTPException(401)
            return user
        except Exception:
            self.logout(request)
            raise HTTPException(401, "Веб-сессия истекла") from None

    def owner(self, request: Request):
        return require_owner(self.current_user(request))

    def logout(self, request):
        with self.lock:
            self.entries.pop(request.session.get("sid"), None)
        request.session.clear()


def session_router(sessions, login):
    router = APIRouter(prefix="/admin")

    @router.get("/session")
    def csrf(request: Request):
        request.session.setdefault("csrf", secrets.token_urlsafe(32))
        return {"csrf": request.session["csrf"]}

    @router.post("/login")
    def sign_in(payload: WebLogin, request: Request):
        sessions.check_csrf(request, payload.csrf)
        AUTH_LIMITS.check(request, "web_login", payload.email.strip().casefold())
        result = login(payload)
        token = result.get("access_token")
        if not token:
            raise HTTPException(401, "Не удалось выполнить вход")
        user = sessions.authenticate("Bearer " + token)
        sessions.create(request, token, user)
        return {"csrf": request.session["csrf"]}

    @router.post("/logout")
    def logout(request: Request):
        sessions.check_csrf(request)
        sessions.logout(request)
        return {"status": "ok"}

    @router.get("/whoami")
    def whoami(user=Depends(sessions.owner)):
        return {"user_id": user.user_id}

    return router

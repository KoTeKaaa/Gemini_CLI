"""Серверные страницы; браузер не получает Supabase-токены."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from .adapter import safe_admin_call
from .subscriptions import MODELS, TOOLS

ROOT = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=ROOT / "templates")


class PanelHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def secured(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend([
                    (b"cache-control", b"no-store"), (b"referrer-policy", b"no-referrer"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self'; "
                     b"base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
                ])
            await send(message)
        await self.app(scope, receive, secured)


def page_router(sessions):
    router = APIRouter()

    @router.get("/admin/login")
    def login(request: Request):
        return TEMPLATES.TemplateResponse(request, "login.html", {})

    @router.get("/admin/")
    def index(request: Request, user=Depends(sessions.owner)):
        rows = safe_admin_call(lambda db: db.table("account_subscriptions").select("*")
                               .order("created_at", desc=True).limit(1000).execute().data)
        return TEMPLATES.TemplateResponse(request, "subscriptions.html", {
            "subscriptions": rows, "models": sorted(MODELS), "features": sorted(TOOLS)})

    router.mount("/panel-static", StaticFiles(directory=ROOT / "static"), name="panel-static")
    return router

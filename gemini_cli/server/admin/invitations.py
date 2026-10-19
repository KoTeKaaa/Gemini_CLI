"""Одноразовый секрет появляется только при выпуске; в БД передаётся SHA-256."""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .adapter import safe_admin_call


class InvitationInput(BaseModel):
    subscription_id: UUID
    ttl_seconds: int = Field(default=86400, ge=60, le=604800, strict=True)


class ActivationInput(BaseModel):
    token: str = Field(min_length=40, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", repr=False)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def issue_invitation(user, payload):
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=payload.ttl_seconds)
    invitation = safe_admin_call(lambda db: db.rpc("issue_subscription_invitation", {
        "actor_id": user.user_id, "target_id": str(payload.subscription_id),
        "secret_hash": token_hash(token), "deadline": expires.isoformat(),
    }).execute().data)
    if not invitation:
        raise HTTPException(409, "Нельзя выпустить ссылку для этой подписки")
    return {"id": invitation, "expires_at": expires.isoformat(),
            "url": os.environ["ADMIN_ORIGIN"] + "/activate#" + token}


def invitation_router(sessions):
    router = APIRouter()

    @router.get("/activation/session")
    def identity(user=Depends(sessions.current_user)):
        return {"user_id": user.user_id}

    @router.post("/admin/api/invitations")
    def issue(payload: InvitationInput, request: Request, user=Depends(sessions.owner)):
        sessions.check_csrf(request)
        return issue_invitation(user, payload)

    @router.post("/activate")
    def activate(payload: ActivationInput, request: Request, user=Depends(sessions.current_user)):
        sessions.check_csrf(request)
        result = safe_admin_call(lambda db: db.rpc("activate_subscription_invitation", {
            "account_id": user.user_id, "secret_hash": token_hash(payload.token),
        }).execute().data)
        if not result:
            raise HTTPException(409, "Ссылка недействительна или недоступна этому аккаунту")
        return {"subscription_id": result}

    return router

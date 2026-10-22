"""Одинаковая валидация подписок для HTTP API и веб-форм."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...tools.definitions import TOOLS
from ..subscriptions import require_subscription
from .adapter import safe_admin_call
from ...protocol.models import MODEL_IDS


MODELS = set(MODEL_IDS)


class SubscriptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID | None = None
    status: Literal["active", "suspended", "revoked"] = "suspended"
    expires_at: datetime
    models: list[str] = Field(max_length=32)
    features: list[str] = Field(max_length=64)
    request_limit: int = Field(ge=0, le=1000000, strict=True)
    window_seconds: int = Field(default=86400, ge=60, le=2678400, strict=True)
    parallel_limit: int = Field(default=1, ge=1, le=8, strict=True)

    @field_validator("models", "features")
    @classmethod
    def known_ids(cls, value, info):
        allowed = MODELS if info.field_name == "models" else set(TOOLS) | {"mcp"}
        if len(value) != len(set(value)) or not set(value) <= allowed:
            raise ValueError("Неизвестные или повторяющиеся идентификаторы прав")
        return value

    @field_validator("expires_at")
    @classmethod
    def aware_expiry(cls, value):
        if value.tzinfo is None:
            raise ValueError("Срок должен включать часовой пояс")
        return value.astimezone(timezone.utc)


class SubscriptionUpdate(SubscriptionInput):
    rights_version: int = Field(ge=1, strict=True)


def change_subscription(user, payload, subscription_id=None):
    values = payload.model_dump(mode="json", exclude={"rights_version"})
    result = safe_admin_call(lambda db: db.rpc("manage_subscription", {
        "actor_id": user.user_id, "subscription_id": str(subscription_id) if subscription_id else None,
        "expected_version": getattr(payload, "rights_version", None), "changes": values,
    }).execute().data)
    if not result:
        raise HTTPException(409, "Подписка изменена, отсутствует или имеет другого владельца")
    return result


def subscription_router(get_user, get_admin, sessions):
    router = APIRouter()

    @router.get("/subscription")
    def own(user=Depends(get_user)):
        return require_subscription(user)

    @router.get("/admin/api/subscriptions")
    def subscriptions(user=Depends(sessions.owner)):
        return safe_admin_call(lambda db: db.table("account_subscriptions").select("*")
                               .order("created_at", desc=True).limit(1000).execute().data)

    @router.post("/admin/api/subscriptions")
    def create(payload: SubscriptionInput, request: Request, user=Depends(sessions.owner)):
        sessions.check_csrf(request)
        return change_subscription(user, payload)

    @router.put("/admin/api/subscriptions/{subscription_id}")
    def update(subscription_id: UUID, payload: SubscriptionUpdate, request: Request,
               user=Depends(sessions.owner)):
        sessions.check_csrf(request)
        return change_subscription(user, payload, subscription_id)

    return router

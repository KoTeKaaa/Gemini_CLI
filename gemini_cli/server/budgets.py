"""Необратимое резервирование вызова: неизвестный расход остаётся учтённым."""

import os
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from .subscriptions import require_subscription


def subscription_limits(user, *, now=None, counter=None) -> dict:
    rights = require_subscription(user)
    sampled = now or datetime.now(timezone.utc)
    seconds = rights["window_seconds"]
    start = int(sampled.timestamp()) // seconds * seconds
    try:
        if counter is None:
            from supabase import create_client
            key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
            if not key:
                raise ValueError("Missing credential")
            admin = create_client(os.environ["SUPABASE_URL"], key)
            def counter(subscription_id, since):
                return admin.table("subscription_requests").select("request_id", count="exact", head=True).eq(
                    "subscription_id", subscription_id).gte("reserved_at", since).execute().count
        used = counter(rights["id"], datetime.fromtimestamp(start, timezone.utc).isoformat())
        if type(used) is not int or used < 0:
            raise ValueError("Missing exact count")
    except Exception:
        return {"kind": "subscription", "unavailable": True,
                "reason": "Не удалось прочитать расход подписки", "fetched_at": sampled.timestamp()}
    return {"kind": "subscription", "limit": rights["request_limit"], "used": used,
            "remaining": max(0, rights["request_limit"] - used), "window_seconds": seconds,
            "window_start": start, "reset_at": start + seconds, "fetched_at": sampled.timestamp(),
            "expires_at": rights["expires_at"], "unavailable": False}


def reserve_request(user, *, operation: str, request_id=None, model=None, features=()):
    # This credential never enters a user context or a browser response.
    from supabase import create_client
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        raise HTTPException(503, "Серверный учёт бюджета не настроен")
    try:
        admin = create_client(os.environ["SUPABASE_URL"], key)
        result = admin.rpc("reserve_subscription_request", {
            "account_id": user.user_id, "call_id": str(request_id or uuid4()),
            "operation_name": operation, "model_id": model, "required_features": sorted(features),
        }).execute().data
    except Exception:
        raise HTTPException(503, "Не удалось зарезервировать бюджет") from None
    errors = {"denied": (403, "Подписка не разрешает вызов"),
              "duplicate": (409, "Запрос уже учтён; повторный вызов запрещён"),
              "exhausted": (429, "Исчерпан бюджет подписки")}
    if result != "reserved":
        code, message = errors.get(result, (503, "Не удалось подтвердить резерв бюджета"))
        raise HTTPException(code, message)

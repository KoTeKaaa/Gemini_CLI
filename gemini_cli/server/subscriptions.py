"""Серверный допуск: права всегда читаются заново, без доверия клиенту."""

from datetime import datetime, timezone

from fastapi import Depends, HTTPException


def require_subscription(user, *, model: str | None = None, features=()) -> dict:
    try:
        rows = user.db.table("account_subscriptions").select("*").eq(
            "user_id", user.user_id).execute().data
        if len(rows) != 1:
            raise HTTPException(403, "Активная подписка отсутствует")
        rights = rows[0]
        expiry = datetime.fromisoformat(rights["expires_at"].replace("Z", "+00:00"))
        if rights["status"] != "active" or expiry <= datetime.now(timezone.utc):
            raise HTTPException(403, "Подписка неактивна или истекла")
        if model is not None and model not in rights["models"]:
            raise HTTPException(403, "Модель недоступна по подписке")
        if not set(features) <= set(rights["features"]):
            raise HTTPException(403, "Возможность недоступна по подписке")
        return rights
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Не удалось проверить права подписки") from None


def working_user_dependency(get_user):
    def working_user(user=Depends(get_user)):
        require_subscription(user)
        return user
    return working_user

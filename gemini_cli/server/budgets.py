"""Необратимое резервирование вызова: неизвестный расход остаётся учтённым."""

import os
from uuid import uuid4

from fastapi import HTTPException


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

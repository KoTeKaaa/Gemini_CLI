"""Единственная граница административного ключа Supabase."""

import os
from fastapi import HTTPException


def admin_client():
    from supabase import create_client
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        raise HTTPException(503, "Серверное управление не настроено")
    return create_client(os.environ["SUPABASE_URL"], key)


def safe_admin_call(operation):
    try:
        return operation(admin_client())
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Операция управления недоступна") from None

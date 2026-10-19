"""Приглашение auth-аккаунта отдельно от выдачи подписки."""

import os
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field

from .adapter import admin_client


class AccountInvitation(BaseModel):
    email: str = Field(max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountConfirmation(BaseModel):
    access_token: str = Field(min_length=20, max_length=8192, repr=False)
    refresh_token: str = Field(min_length=10, max_length=8192, repr=False)
    password: str = Field(min_length=8, max_length=128, repr=False)


def confirm_account(payload, sessions, request):
    from supabase import create_client
    try:
        db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
        result = db.auth.set_session(payload.access_token, payload.refresh_token)
        if not result.session:
            raise ValueError()
        db.auth.update_user({"password": payload.password})
        user = sessions.authenticate("Bearer " + result.session.access_token)
        sessions.create(request, result.session.access_token, user)
    except Exception:
        raise HTTPException(401, "Не удалось подтвердить аккаунт. Откройте действующее приглашение.") from None
    return {"detail": "Пароль установлен. Войдите в CLI; для доступа к серверу нужна отдельная подписка."}


def invite_account(email: str):
    # Do not expose whether an email exists, nor provider errors or credentials.
    try:
        admin_client().auth.admin.invite_user_by_email(email.strip(), options={
            "redirect_to": os.environ["ADMIN_ORIGIN"] + "/account/confirm",
        })
    except Exception:
        pass
    return {"detail": "Если приглашение допустимо, письмо будет отправлено. Подписка выдаётся отдельно."}


def account_router(sessions):
    router = APIRouter()

    @router.post("/account/confirm")
    def confirm(payload: AccountConfirmation, request: Request):
        sessions.check_csrf(request)
        return confirm_account(payload, sessions, request)

    @router.post("/admin/api/accounts/invite")
    def invite(payload: AccountInvitation, request: Request, user=Depends(sessions.owner)):
        sessions.check_csrf(request)
        return invite_account(payload.email)

    return router

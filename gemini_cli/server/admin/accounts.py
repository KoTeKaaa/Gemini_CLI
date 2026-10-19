"""Приглашение auth-аккаунта отдельно от выдачи подписки."""

import os
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .adapter import admin_client


class AccountInvitation(BaseModel):
    email: str = Field(max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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

    @router.post("/admin/api/accounts/invite")
    def invite(payload: AccountInvitation, request: Request, user=Depends(sessions.owner)):
        sessions.check_csrf(request)
        return invite_account(payload.email)

    return router

"""Только бюджет своей подписки; клиент не выбирает account/subscription ID."""

from fastapi import APIRouter, Depends

from .budgets import subscription_limits


def create_quota_router(get_user, snapshot=subscription_limits):
    router = APIRouter()

    @router.get("/limits")
    def limits(refresh: bool = False, user=Depends(get_user)):
        return snapshot(user)

    return router

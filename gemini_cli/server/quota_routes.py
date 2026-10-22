"""Кэш проекта общий для клиентов; доступ проверяется на каждом чтении."""

from fastapi import APIRouter, Depends, HTTPException

from ..protocol.models import MODEL_IDS


def create_quota_router(get_user, service):
    router = APIRouter()

    @router.get("/limits")
    def limits(model: str = MODEL_IDS[0], refresh: bool = False, user=Depends(get_user)):
        if model not in MODEL_IDS:
            raise HTTPException(422, "Неизвестная модель")
        return service.get(model, refresh=refresh)

    return router

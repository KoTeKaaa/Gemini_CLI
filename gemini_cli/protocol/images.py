"""Версия мультимодального wire-контракта и общая проверка обоих режимов."""

import base64
import binascii

from .attachments import ImageAttachment, MAX_IMAGE_BYTES, MAX_IMAGES, MAX_TOTAL_BYTES, validate_batch
from .models import MODEL_IDS

IMAGE_MODELS = frozenset(MODEL_IDS)
IMAGE_PROTOCOL = 1
MAX_WIRE_BYTES = 8 * 1024 * 1024


def encode_images(images: list[ImageAttachment]) -> list[dict]:
    validate_batch(images)
    return [{**image.metadata(), 'data': base64.b64encode(image.data).decode('ascii')} for image in images]


def decode_images(parts: list[dict], model: str) -> list[ImageAttachment]:
    if not isinstance(parts, list) or len(parts) > MAX_IMAGES:
        raise ValueError('Некорректный список изображений')
    if parts and model not in IMAGE_MODELS:
        raise ValueError('Выбранная модель не поддерживает изображения')
    images = []
    for part in parts:
        if not isinstance(part, dict):
            raise ValueError('Некорректное изображение')
        encoded = part.get('data')
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
            raise ValueError('Изображение превышает предел')
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError('Некорректные данные изображения') from exc
        image = ImageAttachment(part.get('name', 'Изображение'), data)
        if part.get('mime_type') != image.mime_type:
            raise ValueError('Тип изображения не соответствует содержимому')
        images.append(image)
    validate_batch(images)
    return images


def validate_payload_images(payload: dict) -> bool:
    model = payload.get('model_name', MODEL_IDS[0])
    rows = [payload, *(payload.get('history') or [])]
    total = 0
    found = False
    for row in rows:
        parts = row.get('images', [])
        if parts:
            if row is not payload and row.get('role') != 'user':
                raise ValueError('Изображения разрешены только в сообщении пользователя')
            images = decode_images(parts, model)
            total += sum(len(image.data) for image in images)
            found = True
    if total > MAX_TOTAL_BYTES:
        raise ValueError('Изображения контекста превышают 4 МиБ')
    return found

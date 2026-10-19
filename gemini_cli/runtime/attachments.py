"""Метаданные в тексте истории; восстановление байтов только из памяти клиента."""

import json
from ..protocol.attachments import MAX_TOTAL_BYTES

MARKER = '\n[Вложения; без байтов при восстановлении: '


def attachment_text(text: str, images: list) -> str:
    if not images:
        return text
    return text + MARKER + json.dumps([image.metadata() for image in images], ensure_ascii=False) + ']'


def restore_images(stored: list[dict], live: list[dict]) -> list[dict]:
    by_content = {row.get('content'): row['images'] for row in live
                  if row.get('role') == 'user' and row.get('images') and MARKER in row.get('content', '')}
    return [{**row, 'images': by_content[row['content']]} if row.get('role') == 'user'
            and row.get('content') in by_content else row for row in stored]


def bound_image_history(history: list[dict]) -> None:
    total = 0
    for row in reversed(history):
        parts = row.get('images', [])
        size = sum(part.get('size', 0) for part in parts)
        if total + size > MAX_TOTAL_BYTES:
            row.pop('images', None)
        else:
            total += size


def missing_image_note(row: dict) -> str:
    if MARKER in row.get('content', '') and not row.get('images'):
        return '\nИзображения недоступны. Попросите пользователя прикрепить их повторно.'
    return ''

"""Локальные файловые операции с явным подтверждением через CLI."""

import json
import logging
import os
from typing import Callable

from .workspace import file_identity, is_sensitive_read_path, resolve_safe_path


def read_files(
    args: dict,
    current_dir: str,
    *,
    approve: Callable[[list[tuple[str, str]]], bool],
    logger: logging.Logger,
) -> str:
    filepaths = args.get("filepaths", [])
    if not filepaths:
        return json.dumps({"error": "Список файлов пуст"})

    planned = []
    for path in filepaths:
        full_path = resolve_safe_path(current_dir, path)
        expected_identity = None
        if full_path is None:
            error = "Ошибка: Доступ заблокирован песочницей"
        elif is_sensitive_read_path(full_path):
            error = "Ошибка: Чтение файла с секретами запрещено"
        else:
            error = None
            try:
                expected_identity = file_identity(os.stat(full_path))
            except FileNotFoundError:
                error = "Ошибка: Файл не найден"
            except OSError as e:
                error = f"Ошибка при чтении файла: {e}"
        planned.append((path, full_path, error, expected_identity))

    readable = [(path, full_path) for path, full_path, error, _ in planned if error is None]
    approved = approve(readable) if readable else False

    results = {}
    for path, full_path, error, expected_identity in planned:
        if error:
            results[path] = error
            continue
        if not approved:
            results[path] = "Ошибка: Чтение отклонено пользователем"
            continue

        try:
            with os.fdopen(os.open(full_path, os.O_RDONLY), "r", encoding="utf-8") as f:
                if file_identity(os.fstat(f.fileno())) != expected_identity:
                    results[path] = "Ошибка: Файл изменился после подтверждения"
                    continue
                content = f.read()
                if file_identity(os.fstat(f.fileno())) != expected_identity:
                    results[path] = "Ошибка: Файл изменился во время чтения"
                    continue
                results[path] = content
        except Exception as e:
            results[path] = f"Ошибка при чтении файла: {str(e)}"
            logger.exception(f"Необработанное исключение: {e}")

    return json.dumps(results, ensure_ascii=False)

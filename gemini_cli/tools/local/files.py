"""Локальные файловые операции с явным подтверждением через CLI."""

import json
import logging
import os
import stat
import tempfile
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


def atomic_write_text(full_path: str, content: str) -> None:
    """Заменить файл через временный в том же каталоге, сохранив его права."""
    temporary_path = None
    try:
        directory = os.path.dirname(full_path)
        os.makedirs(directory, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".gemini-write-", delete=False) as file_obj:
            temporary_path = file_obj.name
            file_obj.write(content)
        if os.path.exists(full_path):
            os.chmod(temporary_path, stat.S_IMODE(os.stat(full_path).st_mode))
        os.replace(temporary_path, full_path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def write_files(
    args: dict,
    current_dir: str,
    *,
    approve: Callable[[list[dict]], bool],
    notify: Callable[[str], None],
    logger: logging.Logger,
) -> str:
    files = args.get("files", [])
    if not files:
        return json.dumps({"error": "Список файлов для записи пуст"}, ensure_ascii=False)
    if not approve(files):
        return json.dumps({"error": "Операция отклонена пользователем из соображений безопасности."},
                          ensure_ascii=False)

    results = []
    for file in files:
        rel_path = file.get("filepath", "")
        content = file.get("content", "")
        full_path = resolve_safe_path(current_dir, rel_path)
        if full_path is None:
            status = "Заблокировано песочницей"
        else:
            try:
                atomic_write_text(full_path, content)
                status = "Успешно записан"
            except Exception as e:
                status = f"Ошибка: {str(e)}"
                logger.exception(f"Необработанное исключение: {e}")
        results.append({"filepath": rel_path, "status": status})
        notify(f"{rel_path}: {status}")
    return json.dumps(results, ensure_ascii=False)

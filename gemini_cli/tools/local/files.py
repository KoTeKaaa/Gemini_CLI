"""Локальные файловые операции с явным подтверждением через CLI."""

import json
import logging
import os
import stat
import tempfile
from typing import Callable

from .workspace import file_identity, is_sensitive_read_path, resolve_safe_path, plan_text_file, read_text_snapshot
from ..results import failure, success


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


def atomic_write_text(full_path: str, content: str, *, newline: str | None = None,
                      validate: Callable[[], None] | None = None) -> None:
    """Заменить файл через временный в том же каталоге, сохранив его права."""
    temporary_path = None
    try:
        directory = os.path.dirname(full_path)
        os.makedirs(directory, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline=newline, dir=directory,
                                         prefix=".gemini-write-", delete=False) as file_obj:
            temporary_path = file_obj.name
            file_obj.write(content)
        if os.path.exists(full_path):
            os.chmod(temporary_path, stat.S_IMODE(os.stat(full_path).st_mode))
        if validate is not None:
            validate()
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
    changes=None, confirm_diff=None, cancelled=lambda: False,
) -> str:
    files = args.get("files", [])
    if not files:
        return json.dumps({"error": "Список файлов для записи пуст"}, ensure_ascii=False)
    from .changes import ChangeSet
    from .write_set import write_set
    return json.dumps(write_set(files, changes or ChangeSet(current_dir), approve=approve,
                               confirm_diff=confirm_diff, notify=notify, cancelled=cancelled), ensure_ascii=False)


def read_file_lines(args: dict, current_dir: str, *, approve,
                    max_lines=500, max_chars=20000) -> dict:
    path, start, end = args.get("filepath"), args.get("start_line"), args.get("end_line")
    if (not isinstance(path, str) or not path or type(start) is not int or type(end) is not int
            or start < 1 or end < start):
        return failure("invalid_arguments", "Нужны путь и включительный диапазон строк от 1")
    try:
        expected = plan_text_file(current_dir, path)
        if not approve(f"Чтение {path!r}, строки {start}–{end}; содержимое будет отправлено модели"):
            return failure("denied", "Чтение отклонено пользователем")
        lines = read_text_snapshot(current_dir, path, expected).splitlines()
    except (OSError, ValueError, UnicodeError):
        return failure("unreadable", "Файл недоступен, изменился, содержит секреты или не является текстовым")
    selected, characters = [], 0
    available = lines[start - 1:end]
    truncated = len(available) > max_lines
    for number, line in enumerate(available[:max_lines], start):
        remaining = max_chars - characters
        if remaining <= 0:
            truncated = True
            break
        selected.append({"line": number, "text": line[:remaining]})
        characters += min(len(line), remaining)
        truncated |= len(line) > remaining
    return success({"filepath": path, "lines": selected}, truncated=truncated)

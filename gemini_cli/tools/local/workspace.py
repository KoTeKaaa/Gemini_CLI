"""Общие проверки путей, секретных файлов и идентичности файла."""

import os
import stat
from pathlib import Path
from typing import Optional


def path_has_links(path: str) -> bool:
    """Не путать Windows 8.3 aliases с symlink/junction в любом компоненте."""
    target = Path(os.path.abspath(path))
    for part in (target, *target.parents):
        try:
            info = os.lstat(part)
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            return True
    return False


def resolve_safe_path(base_dir: str, path: str) -> Optional[str]:
    resolved_base = os.path.realpath(base_dir)
    resolved_target = os.path.realpath(os.path.join(base_dir, path))
    try:
        if os.path.commonpath((resolved_base, resolved_target)) == resolved_base:
            return resolved_target
    except ValueError:
        pass
    return None


def is_sensitive_read_path(path: str) -> bool:
    parts = [part.casefold() for part in os.path.normpath(path).split(os.sep)]
    name = parts[-1]
    return (any(part == ".env" or part.startswith(".env.") for part in parts)
            or name in {".envrc", ".netrc", ".npmrc", ".pypirc", "credentials.json",
                        "service-account.json", "service_account.json", "session.json",
                        "id_rsa", "id_ed25519"}
            or name.endswith((".pem", ".key")))


def file_identity(file_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (file_stat.st_dev, file_stat.st_ino, file_stat.st_size,
            file_stat.st_mtime_ns, file_stat.st_ctime_ns)


def plan_text_file(root: str, path: str, *, max_bytes=2 * 1024 * 1024) -> tuple:
    full_path = resolve_safe_path(root, path)
    if full_path is None or is_sensitive_read_path(full_path):
        raise ValueError("Доступ к файлу запрещён")
    info = os.stat(full_path)
    if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
        raise ValueError("Нужен обычный файл допустимого размера")
    if os.name == "nt":
        # CPython Windows stat(path).ctime и fstat(fd).ctime имеют разный смысл.
        # Снимок и последующее чтение используют один источник метаданных.
        with os.fdopen(os.open(full_path, os.O_RDONLY | os.O_BINARY), "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (not os.path.samestat(info, opened) or info.st_size != opened.st_size
                    or info.st_mtime_ns != opened.st_mtime_ns):
                raise ValueError("Файл изменился во время выбора")
            info = opened
    return full_path, file_identity(info)


def read_binary_snapshot(root: str, path: str, expected: tuple, *, max_bytes=2 * 1024 * 1024) -> bytes:
    if plan_text_file(root, path, max_bytes=max_bytes) != expected:
        raise ValueError("Файл изменился после подтверждения")
    flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(os.open(expected[0], flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or file_identity(info) != expected[1]:
            raise ValueError("Файл изменился после подтверждения")
        data = stream.read(max_bytes + 1)
        if len(data) > max_bytes or file_identity(os.fstat(stream.fileno())) != expected[1]:
            raise ValueError("Файл изменился во время чтения")
    return data


def read_text_snapshot(root: str, path: str, expected: tuple, *, max_bytes=2 * 1024 * 1024) -> str:
    data = read_binary_snapshot(root, path, expected, max_bytes=max_bytes)
    if b"\x00" in data:
        raise ValueError("Бинарный файл пропущен")
    return data.decode("utf-8")

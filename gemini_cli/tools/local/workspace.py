"""Общие проверки путей, секретных файлов и идентичности файла."""

import os
from typing import Optional


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

"""Ограниченные настройки веб-инструментов из серверного окружения."""

import os


def positive_int(name: str, default: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        return value if 1 <= value <= maximum else default
    except ValueError:
        return default


SEARCH_PER_MINUTE = positive_int("SEARCH_PER_MINUTE", 10, 60)
READ_PER_MINUTE = positive_int("READ_PER_MINUTE", 30, 120)
WEB_TIMEOUT_SECONDS = positive_int("WEB_TIMEOUT_SECONDS", 20, 30)
WEB_MAX_BYTES = positive_int("WEB_MAX_BYTES", 2 * 1024 * 1024, 2 * 1024 * 1024)
WEB_MAX_CHARS = positive_int("WEB_MAX_CHARS", 20000, 20000)
WEB_MAX_REDIRECTS = positive_int("WEB_MAX_REDIRECTS", 3, 3)

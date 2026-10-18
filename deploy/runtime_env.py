"""Создать защищённое окружение из явного списка runtime-настроек."""

import argparse
from pathlib import Path

REQUIRED = ("API_KEY", "SUPABASE_URL", "SUPABASE_ANON_KEY")
OPTIONAL = ("TAVILY_API_KEY", "SEARCH_PER_MINUTE", "READ_PER_MINUTE", "WEB_TIMEOUT_SECONDS",
            "WEB_MAX_BYTES", "WEB_MAX_CHARS", "WEB_MAX_REDIRECTS")


def build_environment(source: Path, destination: Path) -> None:
    values = {}
    for line in source.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key in (*REQUIRED, *OPTIONAL):
            if key in values:
                raise ValueError("Повтор настройки серверного окружения")
            values[key] = value
    if any(not values.get(key) for key in REQUIRED):
        raise ValueError("Не заданы обязательные настройки серверного окружения")
    destination.write_text("".join(f"{key}={values[key]}\n" for key in (*REQUIRED, *OPTIONAL)
                                   if values.get(key)), encoding="utf-8")
    destination.chmod(0o600)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    build_environment(args.source, args.destination)

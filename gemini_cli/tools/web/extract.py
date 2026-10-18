"""Извлечение из переданных байтов; парсер не загружает URL."""

import json

from ..results import failure, success
from .fetch import fetch_url
from .settings import WEB_MAX_CHARS


def extract_page(page, *, max_chars=WEB_MAX_CHARS) -> dict:
    if page.content_type == "text/plain":
        title, text = "", page.body.decode("utf-8", errors="replace")
    elif page.content_type in {"text/html", "application/xhtml+xml"}:
        from trafilatura import extract
        result = extract(page.body, output_format="json", with_metadata=True,
                         include_comments=False, include_tables=True,
                         date_extraction_params={"extensive_search": False})
        data = json.loads(result) if result else {}
        title, text = data.get("title") or "", data.get("text") or ""
    else:
        return failure("unsupported_type", "Неподдерживаемый тип страницы")
    if not text.strip():
        return failure("empty_page", "На странице не найден полезный текст")
    return success({"url": page.url, "final_url": page.final_url,
                    "title": title[:500], "text": text[:max_chars]},
                   truncated=len(text) > max_chars)


def read_url(url: str) -> dict:
    try:
        return extract_page(fetch_url(url))
    except ValueError:
        return failure("fetch_failed", "URL недоступен, запрещён или превышает ограничения")
    except Exception:
        return failure("extract_failed", "Не удалось извлечь текст страницы")

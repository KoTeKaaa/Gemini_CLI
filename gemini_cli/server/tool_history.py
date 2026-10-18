"""Фильтрация только постоянной истории, без изменения текущего хода."""

import json

REDACTED_READ_RESULT = '{"status":"redacted","message":"Результат чтения файлов не сохраняется"}'
PRIVATE_TOOLS = {"search_text", "read_file_lines", "replace_in_file"}
SAFE_ARGUMENTS = {"filepath", "start_line", "end_line", "path", "pattern"}


def persistent_tool_message(role: str, name: str | None, content: str,
                            args: dict | None) -> tuple[str, dict | None]:
    if name in PRIVATE_TOOLS and role in {"model", "tool"}:
        args = {key: value for key, value in (args or {}).items()
                if key in SAFE_ARGUMENTS and isinstance(value, (str, int))}
        content = json.dumps({"status": "redacted", "message": "Содержимое инструмента не сохраняется"},
                             ensure_ascii=False)
    elif role == "tool" and name == "read_local_files":
        content = REDACTED_READ_RESULT
    elif role == "tool" and name in {"web_search", "read_url"}:
        try:
            result = json.loads(content)
            data = result.get("data", {})
            safe = {key: str(data[key])[:2048] for key in ("url", "final_url", "title") if key in data}
            if "text" in data:
                safe["text"] = str(data["text"])[:1000]
            if "results" in data:
                safe["results"] = [{key: str(item.get(key, ""))[:500]
                                    for key in ("title", "url", "snippet")}
                                   for item in data["results"][:5] if isinstance(item, dict)]
            content = json.dumps({"status": result.get("status"), "data": safe,
                                  "truncated": True}, ensure_ascii=False)
        except (ValueError, TypeError, AttributeError):
            content = '{"status":"redacted"}'
    return content, args

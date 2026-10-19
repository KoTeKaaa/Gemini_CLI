"""Фильтрация только постоянной истории, без изменения текущего хода."""

import json

REDACTED_READ_RESULT = '{"status":"redacted","message":"Результат чтения файлов не сохраняется"}'
PRIVATE_TOOLS = {"search_text", "read_file_lines", "replace_in_file"}
SAFE_ARGUMENTS = {"filepath", "start_line", "end_line", "path"}


def bounded_tool_result(content: str, max_bytes=8192) -> str:
    encoded = content.encode("utf-8", errors="replace")
    if len(json.dumps(content, ensure_ascii=False).encode("utf-8")) <= max_bytes:
        return content
    prefix = encoded[:max_bytes // 4].decode("utf-8", errors="ignore")
    return json.dumps({"status": "truncated", "truncated": True,
                       "message": "Результат усечён. Читайте нужный диапазон через read_file_lines/search_text.",
                       "output": prefix}, ensure_ascii=False)


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
            if not isinstance(data, dict):
                raise ValueError("Invalid web history")
            safe = {key: str(data[key])[:2048] for key in ("url", "final_url", "title") if key in data}
            if "text" in data:
                safe["text"] = str(data["text"])[:1000]
            if "results" in data:
                if not isinstance(data["results"], list):
                    raise ValueError("Invalid web sources")
                safe["results"] = [{key: str(item.get(key, ""))[:500]
                                    for key in ("title", "url", "snippet")}
                                   for item in data["results"][:5] if isinstance(item, dict)]
            content = json.dumps({"status": result.get("status"), "data": safe,
                                  "truncated": True}, ensure_ascii=False)
        except (ValueError, TypeError, AttributeError, KeyError):
            content = '{"status":"redacted"}'
    return content, args


def trim_history(history: list[dict], limit: int = 20, tool_content_limit: int = 4) -> list[dict]:
    last_user = next((index for index in range(len(history) - 1, -1, -1)
                      if history[index].get("role") == "user"), len(history))
    start = min(max(0, len(history) - limit), last_user)
    trimmed = [dict(item) for item in history[start:]]
    while trimmed and trimmed[0].get("role") != "user":
        trimmed = trimmed[1:]

    tool_count = 0
    current_turn_start = next((index for index in range(len(trimmed) - 1, -1, -1)
                               if trimmed[index].get("role") == "user"), len(trimmed))
    for msg in reversed(trimmed[:current_turn_start]):
        if msg.get("role") == "tool":
            tool_count += 1
            if tool_count > tool_content_limit:
                msg["content"] = '{"status": "already_processed"}'

    return trimmed


def persistent_history_rows(messages: list[dict], before_user_content: str | None = None) -> list[dict]:
    if before_user_content is not None:
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") == "user" and messages[index].get("content") == before_user_content:
                messages = messages[:index]
                break
    restored = []
    for message in messages:
        content, args = persistent_tool_message(message["role"], message.get("name"),
                                                message.get("content") or "", message.get("args"))
        restored.append({key: message.get(key) for key in
                         ("role", "name", "call_id", "thought_signature")}
                        | {"content": content, "args": args})
    return restored

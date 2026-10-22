"""Фильтрация только постоянной истории, без изменения текущего хода."""

import json
from ..protocol.limits import MAX_TOOL_RESULT_WIRE_BYTES

REDACTED_READ_RESULT = '{"status":"redacted","message":"Результат чтения файлов не сохраняется"}'
PRIVATE_TOOLS = {"search_text", "read_file_lines", "replace_in_file"}
SAFE_ARGUMENTS = {"filepath", "start_line", "end_line", "path"}


def bounded_tool_result(content: str, max_bytes=MAX_TOOL_RESULT_WIRE_BYTES) -> str:
    if max_bytes < 1024:
        raise ValueError("Слишком малый предел результата инструмента")
    encoded = content.encode("utf-8", errors="replace")
    if len(json.dumps(content).encode("utf-8")) <= max_bytes:
        return content
    prefix = encoded[:max_bytes // 4].decode("utf-8", errors="ignore")
    while True:
        result = json.dumps({"status": "truncated", "truncated": True,
                             "message": "Результат усечён. Читайте диапазон через read_file_lines/search_text.",
                             "output": prefix}, ensure_ascii=False)
        if len(json.dumps(result).encode()) <= max_bytes:
            return result
        prefix = prefix[:len(prefix) // 2]


def persistent_tool_message(role: str, name: str | None, content: str,
                            args: dict | None) -> tuple[str, dict | None]:
    if isinstance(name, str) and name.startswith("mcp_") and role in {"model", "tool"}:
        return '{"status":"redacted","message":"Содержимое MCP не сохраняется"}', {} if args is not None else None
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
                         ("role", "name", "call_id", "thought_signature", "id", "turn_id",
                          "request_id", "event_index", "status", "sequence")}
                        | {"content": content, "args": args})
    return complete_tool_pairs(restored)


def complete_tool_pairs(history):
    repaired, pending = [], []
    def flush():
        for call in pending:
            repaired.append({"role": "tool", "name": call["name"],
                "call_id": call.get("call_id"), "thought_signature": None, "args": None,
                "id": None, "turn_id": None, "request_id": None, "event_index": None,
                "status": None, "sequence": None,
                "content": json.dumps({
                    "status": "interrupted", "message":
                    "Ход прерван; сохранённый результат отсутствует. Действие могло выполниться. Не повторять автоматически."},
                    ensure_ascii=False)})
        pending.clear()
    for row in history:
        role = row.get("role")
        if role == "model" and row.get("name"):
            pending.append(row)
        elif role == "tool":
            match = next((call for call in pending if call.get("name") == row.get("name")
                          and (row.get("call_id") is None or call.get("call_id") == row.get("call_id"))), None)
            if match is not None:
                row = {**row, "call_id": match.get("call_id")}
                pending.remove(match)
        else:
            flush()
        repaired.append(row)
    flush()
    return repaired

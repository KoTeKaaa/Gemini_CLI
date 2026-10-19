"""Диспетчер прежних локальных инструментов с сохранением порядка вызовов."""

import logging
import json
from typing import Callable, Mapping

from ..tools.definitions import TOOLS
from ..tools.results import failure
from ..runtime.history import bounded_tool_result


def execute_tool_calls(
    tool_calls: list[dict], history: list[dict], current_dir: str, *,
    handlers: Mapping[str, Callable[[dict, str], str]], logger: logging.Logger,
) -> None:
    for call in tool_calls:
        tool_name = call.get("name")
        history.append({
            "role": "model", "content": f"[Вызов локального инструмента: {tool_name}]",
            "name": tool_name, "args": call.get("args", {}), "call_id": call.get("call_id"),
            "thought_signature": call.get("thought_signature")
        })

    for call in tool_calls:
        tool_name = call.get("name")
        tool_args = call.get("args", {})
        if tool_name in TOOLS and tool_name in handlers:
            try:
                tool_result = handlers[tool_name](tool_args, current_dir)
            except Exception:
                tool_result = json.dumps(failure("tool_error", "Инструмент не выполнен"), ensure_ascii=False)
        else:
            tool_result = f"Ошибка: Инструмент {tool_name} не поддерживается клиентом."
        history.append({
            "role": "tool", "name": tool_name, "content": bounded_tool_result(tool_result),
            "call_id": call.get("call_id")
        })
        logged_name = tool_name if tool_name in TOOLS else "unknown"
        logger.info("Tool вызов: %s", logged_name)

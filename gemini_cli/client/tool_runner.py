"""Диспетчер прежних локальных инструментов с сохранением порядка вызовов."""

import logging
import json
from uuid import uuid4
from typing import Callable, Mapping

from ..tools.definitions import TOOLS
from ..tools.results import failure
from ..runtime.history import bounded_tool_result


def execute_tool_calls(
    tool_calls: list[dict], history: list[dict], current_dir: str, *,
    handlers: Mapping[str, Callable[[dict, str], str]], logger: logging.Logger,
    state=None,
) -> None:
    for call in tool_calls:
        tool_name = call.get("name")
        history.append({
            "role": "model", "content": f"[Вызов локального инструмента: {tool_name}]",
            "name": tool_name, "args": call.get("args", {}), "call_id": call.get("call_id"),
            "thought_signature": call.get("thought_signature"), "id": str(uuid4()),
            "turn_id": getattr(state, "turn_id", None), "status": "running"
        })

    for index, call in enumerate(tool_calls):
        tool_name = call.get("name")
        step_id = f"{getattr(state, 'request_id', '')}:{index}"
        def record(status):
            if state is not None:
                state.record({"type": "step", "step_id": step_id,
                              "name": tool_name if tool_name in TOOLS else "unknown",
                              "call_id": call.get("call_id"), "status": status})
        record("queued")
        tool_args = call.get("args", {})
        if state is not None and state.cancelled.is_set():
            tool_result = json.dumps(failure("cancelled", "Ход отменён; инструмент не запущен"), ensure_ascii=False)
        elif tool_name in TOOLS and tool_name in handlers:
            record("running")
            try:
                tool_result = handlers[tool_name](tool_args, current_dir)
            except Exception:
                tool_result = json.dumps(failure("tool_error", "Инструмент не выполнен"), ensure_ascii=False)
        else:
            tool_result = f"Ошибка: Инструмент {tool_name} не поддерживается клиентом."
        status = "completed"
        try:
            result = json.loads(tool_result)
            if isinstance(result, dict):
                status = result.get("status", "completed")
                if result.get("error") or result.get("exit_code", 0) not in (None, 0):
                    status = "failed"
        except (ValueError, TypeError):
            if str(tool_result).startswith("Ошибка"):
                status = "failed"
            elif "отменен" in str(tool_result) or "отменено" in str(tool_result):
                status = "cancelled"
        if state is not None and state.cancelled.is_set():
            status = "cancelled" if status != "completed" else "completed"
            if '"code": "cancelled"' in tool_result:
                status = "skipped"
        record({"ok": "completed", "error": "failed", "timeout": "failed"}.get(status, status))
        history.append({
            "role": "tool", "name": tool_name, "content": bounded_tool_result(tool_result),
            "call_id": call.get("call_id"), "id": str(uuid4()),
            "turn_id": getattr(state, "turn_id", None), "status": "running"
        })
        logged_name = tool_name if tool_name in TOOLS else "unknown"
        logger.info("Tool вызов: %s", logged_name)

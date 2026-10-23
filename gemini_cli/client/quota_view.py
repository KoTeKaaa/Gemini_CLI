"""Бюджет подписки Remote и асинхронный контекст для строки ввода."""

from datetime import datetime, timezone
from threading import Lock, Thread
import time
import math

from prompt_toolkit.utils import get_cwidth

from .input import safe_label
def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def value(value):
    return "—" if number(value) is None else f"{value:g}"


def limits_text(data: dict) -> str:
    lines = ["Бюджет подписки сервиса. Это не квота Gemini/Tavily."]
    if data.get("unavailable"):
        lines.append(safe_label(str(data.get("reason") or "Данные недоступны")))
    else:
        lines.append(f"Предел: {value(data.get('limit'))}; учтено вызовов: {value(data.get('used'))}; "
                     f"остаток: {value(data.get('remaining'))}")
        seconds = data.get("window_seconds")
        lines.append("Окно: " + ("сутки (UTC)" if seconds == 86400 else value(seconds) + " секунд"))
        for key, title in (("fetched_at", "Получено"), ("reset_at", "Сброс окна")):
            stamp = number(data.get(key))
            try:
                text = datetime.fromtimestamp(stamp, timezone.utc).isoformat() if stamp is not None else "—"
            except (ValueError, OverflowError, OSError):
                text = "—"
            lines.append(f"{title}: {text}")
        lines.append("Включает генерацию, продолжения, сжатие и серверный поиск; резерв не возвращается при сбое.")
    lines.append("Пример: /limits refresh. Снимок обновляется без вызова модели.")
    return "\n".join(lines)


def shorten(text: str, width: int) -> str:
    text = safe_label(text)
    if get_cwidth(text) <= width:
        return text
    result, used = "", 0
    for char in text:
        size = get_cwidth(char)
        if used + size > max(0, width - 1):
            break
        result, used = result + char, used + size
    return result + ("…" if width else "")


def status_line(workspace, model, mode, chat, context, budget, width) -> str:
    # Reduce names together so the quota fields survive on modest terminals.
    fields = [workspace, model, mode, chat, "контекст " + context]
    if mode == "remote":
        remaining = None if budget.get("unavailable") else budget.get("remaining")
        fields.append("подписка " + value(remaining) + "/" + value(budget.get("limit")))
    budget = max(1, (width - sum(get_cwidth(s) for s in fields[2:]) - 18) // 2)
    fields[0], fields[1], fields[3] = shorten(workspace, budget), shorten(model, budget), shorten(chat, max(4, budget))
    return shorten(" · ".join(fields), max(0, width))


class PromptStatus:
    def __init__(self):
        self.key, self.data, self.context = None, {}, {}
        self.next_fetch, self.busy = 0, False
        self.pending = None
        self.lock = Lock()

    def update(self, client, key, model, payload, invalidate):
        with self.lock:
            if key != self.key:
                self.key, self.data, self.context, self.next_fetch = key, {}, {}, 0
            if self.busy:
                self.pending = (client, key, model, payload, invalidate)
                return
            if time.monotonic() < self.next_fetch:
                return
            self.busy = True
            self.next_fetch = time.monotonic() + 30
        def read():
            data, context = {}, {}
            try:
                if client.mode == "remote":
                    result = client.limits(model)
                    data = result if isinstance(result, dict) else {}
            except Exception:
                pass
            try:
                result = client.context_info(payload)
                context = result if isinstance(result, dict) else {}
            except Exception:
                pass
            with self.lock:
                if self.key == key:
                    self.data, self.context = data, context
                self.busy = False
                pending, self.pending = self.pending, None
            invalidate()
            if pending:
                self.update(*pending)
        Thread(target=read, daemon=True).start()

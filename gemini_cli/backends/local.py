"""Local вызывает общий provider в процессе CLI; HTTP-сервер не поднимается."""

from pathlib import Path
from threading import Event

from .base import StreamResult
from .genai import create_provider, stream_events, to_gemini
from ..client.local_chats import LocalChats
from ..protocol.models import MODEL_IDS
from ..protocol.images import validate_payload_images
from ..runtime.history import persistent_history_rows
from ..runtime.attachments import restore_images
from ..tools.definitions import TOOLS
from ..tools.results import failure


class LocalBackend:
    mode = "local"

    def __init__(self, api_key: str, root: Path, *, profile="default", provider=None, chats=None, tavily_key=None):
        self.api_key, self.provider = api_key, provider
        self.tavily_key = tavily_key
        self.chats = chats or LocalChats(root, profile)

    def get_chats(self):
        return self.chats.list()

    def create_chat(self, title):
        return self.chats.create(title)

    def delete_chat(self, chat_id):
        return self.chats.delete(chat_id)

    def web_tool(self, kind, payload):
        if kind == "read":
            from ..tools.web.extract import read_url
            return read_url(payload.get("url"))
        if kind == "search":
            if not self.tavily_key:
                return failure("unavailable", "Личный ключ Tavily не настроен; чтение URL доступно")
            from ..tools.web.search import search
            result = search(payload.get("query"), payload.get("max_results", 5), api_key=self.tavily_key)
            if result.get("status") == "error" and result.get("error", {}).get("code") == "unavailable":
                return failure("unavailable", "Проверьте личный ключ Tavily в /settings")
            return result
        return failure("invalid_arguments", "Неизвестный веб-инструмент")

    def stream_chat_cancellable(self, payload, cancelled):
        return self.stream_chat(payload, cancelled=cancelled)

    def stream_chat(self, payload: dict, *, cancelled=None) -> StreamResult:
        try:
            validate_payload_images(payload)
            message = payload.get("message", "")
            history = payload.get("history") or []
            continuing = payload.get("continue_after_tool", False)
            ending = payload.get("end_tool_turn", False)
            if payload.get("model_name", MODEL_IDS[0]) not in MODEL_IDS:
                raise ValueError("Неизвестная модель")
            if not isinstance(message, str) or len(message) > 32768 or len(history) > 100:
                raise ValueError("Превышен предел запроса")
            if ending and not continuing:
                raise ValueError("Завершение допустимо после инструмента")
            if continuing:
                if message.strip() or not history or history[-1].get("role") != "tool":
                    raise ValueError("Ожидается результат инструмента")
            elif not message.strip():
                raise ValueError("Сообщение пусто")
            if not set(payload.get("supported_tools") or []) <= set(TOOLS):
                raise ValueError("Неизвестный инструмент")
            chat_id = payload.get("chat_id")
            stored = self.chats.read(chat_id) if chat_id else None
            if stored is not None:
                if continuing:
                    start = next((i for i in range(len(history)-1, -1, -1) if history[i]["role"] == "user"), None)
                    if start is None:
                        raise ValueError("Нет исходного сообщения")
                    history = restore_images(persistent_history_rows(stored, history[start]["content"]), history) + history[start:]
                else:
                    history = restore_images(persistent_history_rows(stored), history)
            contents = to_gemini(history + ([] if continuing else [{"role": "user", "content": message, "images": payload.get("images", [])}]))
        except LookupError:
            return StreamResult(404, detail="Чат не найден в локальном профиле")
        except (ValueError, TypeError, KeyError, AttributeError):
            return StreamResult(400, detail="Некорректный локальный запрос")

        parent_cancelled, closed = cancelled, Event()
        class Cancelled:
            def is_set(self):
                return closed.is_set() or (parent_cancelled is not None and parent_cancelled.is_set())
        cancelled = Cancelled()

        def generate():
            full_text, has_calls, failed = "", False, False
            try:
                if cancelled.is_set():
                    return
                if chat_id:
                    if continuing:
                        batch = payload["history"]
                        start = len(batch) - 1
                        while start and batch[start - 1]["role"] == "tool":
                            start -= 1
                        self.chats.append(chat_id, batch[start:])
                    else:
                        self.chats.append(chat_id, [{"role": "user", "content": message}])
                if ending:
                    text = "Достигнут предел продолжений инструментов. Последние результаты сохранены; продолжите новым сообщением."
                    if chat_id:
                        self.chats.append(chat_id, [{"role": "model", "content": text}])
                    yield {"type": "text", "content": text}
                    return
                if self.provider is None:
                    self.provider = create_provider(self.api_key)
                for event in stream_events(self.provider, model=payload.get("model_name", MODEL_IDS[0]),
                                           contents=contents, supported_tools=payload.get("supported_tools"),
                                           cancelled=cancelled.is_set,
                                           permitted_tools=set(TOOLS) - ({"web_search"} if not self.tavily_key else set())):
                    if event["type"] == "text":
                        full_text += event["content"]
                    elif event["type"] == "tool_call":
                        if chat_id:
                            if not has_calls and full_text:
                                self.chats.append(chat_id, [{"role": "model", "content": full_text}])
                            self.chats.append(chat_id, [{**event, "role": "model", "content": "Вызов инструмента"}])
                        has_calls = True
                    elif event["type"] == "error":
                        failed = True
                    yield event
                if chat_id and full_text and not has_calls and not failed and not cancelled.is_set():
                    self.chats.append(chat_id, [{"role": "model", "content": full_text}])
            except Exception:
                yield {"type": "error", "content": "Не удалось выполнить локальный запрос или сохранить историю"}
        return StreamResult(events=generate(), on_close=closed.set)

    def close(self):
        self.chats.close()
        close = getattr(self.provider, "close", None)
        if close:
            close()
        self.api_key, self.provider = "", None
        self.tavily_key = None

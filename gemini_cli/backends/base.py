"""Нейтральный контракт UI/runner: ни HTTP, ни SDK не определяют интерфейс."""

from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol, runtime_checkable


@dataclass
class StreamResult:
    status_code: int = 200
    events: Iterable[dict] = field(default_factory=tuple)
    detail: str = ""
    on_close: Callable[[], None] = field(default=lambda: None, repr=False)

    def json(self):
        return {"detail": self.detail}

    def close(self):
        try:
            close = getattr(self.events, "close", None)
            if close:
                close()
        finally:
            self.on_close()


@runtime_checkable
class Backend(Protocol):
    mode: str

    def get_chats(self) -> list[dict] | None: ...

    def create_chat(self, title: str) -> dict | None: ...

    def delete_chat(self, chat_id: str) -> bool: ...

    def stream_chat(self, payload: dict) -> StreamResult: ...

    def web_tool(self, kind: str, payload: dict) -> dict: ...

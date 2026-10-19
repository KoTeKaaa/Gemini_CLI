"""Remote HTTP adapter: не импортирует UI или серверные SDK."""

from typing import Optional, List, Dict, Any
import requests

from ..client.profiles import canonical_origin
from ..tools.results import failure


class RemoteBackend:
    mode = "remote"

    def __init__(self, base_url: str, *, notify=lambda message: None, transport=None):
        self.base_url = canonical_origin(base_url)
        self.notify, self.transport = notify, transport or requests
        self.token = None

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _authorized_request(self, request):
        return request()

    def web_tool(self, kind: str, payload: dict) -> dict:
        try:
            response = self._authorized_request(lambda: self.transport.post(
                f"{self.base_url}/tools/web/{kind}", json=payload, headers=self.headers,
                timeout=25, allow_redirects=False))
            with response:
                if response.status_code != 200:
                    return failure("network", "Веб-инструмент недоступен")
                result = response.json()
                if not isinstance(result, dict) or result.get("status") not in {"ok", "error"}:
                    return failure("invalid_response", "Некорректный ответ веб-инструмента")
                return result
        except (requests.RequestException, ValueError):
            return failure("network", "Сетевая ошибка веб-инструмента; автоматического повтора нет")

    def get_chats(self) -> Optional[List[Dict[str, Any]]]:
        try:
            r = self._authorized_request(lambda: self.transport.get(
                f"{self.base_url}/chats", headers=self.headers, timeout=30,
                allow_redirects=False))
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401:
                self.notify("Сессия истекла. Войдите снова.")
            else:
                self.notify(f"Не удалось получить список чатов (код {r.status_code}).")
            return None
        except Exception as e:
            self.notify("Не удалось получить чаты")
            return None

    def create_chat(self, title: str) -> Optional[Dict[str, Any]]:
        try:
            r = self._authorized_request(lambda: self.transport.post(
                f"{self.base_url}/chats",
                json={"title": title},
                headers=self.headers,
                timeout=30,
                allow_redirects=False,
            ))
            if r.status_code == 200:
                return r.json()
            return None
        except Exception as e:
            self.notify("Не удалось создать чат")
            return None

    def delete_chat(self, chat_id: str) -> bool:
        try:
            r = self._authorized_request(lambda: self.transport.delete(
                f"{self.base_url}/chats/{chat_id}",
                headers=self.headers,
                timeout=30,
                allow_redirects=False,
            ))
            return r.status_code == 200
        except Exception as e:
            self.notify("Не удалось удалить чат")
            return False

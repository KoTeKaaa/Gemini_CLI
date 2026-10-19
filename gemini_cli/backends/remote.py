"""Remote HTTP adapter: не импортирует UI или серверные SDK."""

from typing import Optional, List, Dict, Any
import requests
from pathlib import Path
import json
import socket
from uuid import uuid4

from ..client.profiles import canonical_origin, RemoteSessions
from ..tools.results import failure
from .base import StreamResult
from ..protocol.images import IMAGE_PROTOCOL, validate_payload_images


def interrupt_http(response):
    # requests has no public cancel API; shutdown the active socket before close
    # so a concurrent urllib3 read releases its buffered-reader lock promptly.
    raw = getattr(response, "raw", None)
    connection = getattr(raw, "_connection", None)
    sock = getattr(connection, "sock", None)
    if sock is None:
        sock = raw
        for attribute in ("_fp", "fp", "raw", "_sock"):
            sock = getattr(sock, attribute, None)
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    response.close()


def decode_sse(response):
    data = []
    size = 0
    def decode():
        value = json.loads("\n".join(data))
        if not isinstance(value, dict) or value.get("type") not in {"text", "tool_call", "error", "usage", "done"}:
            raise ValueError()
        if value["type"] in {"text", "error"} and not isinstance(value.get("content"), str):
            raise ValueError()
        if value["type"] == "tool_call" and (not isinstance(value.get("name"), str)
                                               or not isinstance(value.get("args"), dict)):
            raise ValueError()
        return value
    try:
        for raw in response.iter_lines():
            for line in raw.decode("utf-8").splitlines() or [""]:
                if not line and data:
                    yield decode()
                    data, size = [], 0
                elif line.startswith("data:"):
                    size += len(line)
                    if size > 65536:
                        raise ValueError()
                    data.append(line[5:].lstrip())
                    # Existing servers/fixtures also emit one JSON per data line.
                    try:
                        json.loads("\n".join(data))
                    except ValueError:
                        continue
                    yield decode()
                    data, size = [], 0
        if data:
            yield decode()
    except (requests.RequestException, ValueError, UnicodeError):
        yield {"type": "error", "content": "Поток прерван или содержит некорректное событие"}
    finally:
        close = getattr(response, "close", None)
        if close:
            close()


def events_from_response(response):
    yield from response.events if isinstance(response, StreamResult) else decode_sse(response)


class RemoteBackend:
    mode = "remote"

    def __init__(self, base_url: str, *, notify=lambda message: None, transport=None,
                 profile_root=None, legacy_session=None, credentials=None):
        self.base_url = canonical_origin(base_url)
        self.notify, self.transport = notify, transport or requests
        self.token = None
        self.account_id = None
        root = profile_root or Path.home() / ".gemini_cli" / "profiles"
        self.sessions = RemoteSessions(root, self.base_url)
        self.legacy_session = legacy_session or root.parent / "session.json"
        self.credentials = credentials

    def set_token(self, token: str):
        self.token = token
        if self.account_id is None:
            self.account_id = (self.sessions.load().get("user") or {}).get("id")

    def _load_session_token(self):
        if not self.sessions.load():
            self.sessions.migrate(self.legacy_session)
        data = self.sessions.load(self.account_id)
        self.account_id = (data.get("user") or {}).get("id")
        return data.get("access_token")

    def login(self) -> bool:
        token = self._load_session_token()
        if token:
            self.token = token
            return True
        while self.credentials:
            values = self.credentials()
            if values is None:
                return False
            email, password = values
            if not email or not password:
                self.notify("Email и пароль обязательны")
                continue
            try:
                response = self.transport.post(f"{self.base_url}/auth/login",
                    json={"email": email, "password": password}, timeout=30,
                    allow_redirects=False)
                try:
                    if response.status_code == 401:
                        self.notify("Не удалось войти. Проверьте данные аккаунта.")
                        continue
                    if response.status_code != 200:
                        self.notify("Вход временно недоступен")
                        return False
                    data = response.json()
                    self.sessions.save(data)
                    self.token = data["access_token"]
                    self.account_id = data["user"]["id"]
                    return True
                finally:
                    response.close()
            except (requests.RequestException, ValueError, OSError):
                self.notify("Не удалось войти или сохранить привязанную сессию")
                return False
        return False

    def _renew_session(self, *, interactive=True) -> bool:
        previous = self.sessions.load(self.account_id)
        refresh = previous.get("refresh_token")
        if refresh:
            try:
                response = self.transport.post(f"{self.base_url}/auth/refresh",
                    json={"refresh_token": refresh}, timeout=30, allow_redirects=False)
                try:
                    if response.status_code == 200:
                        data = response.json()
                        self.sessions.save(data, expected_account=previous["user"]["id"])
                        self.token = data["access_token"]
                        return True
                    if response.status_code not in (400, 401, 403):
                        self.notify("Сервер временно не может обновить сессию")
                        return False
                finally:
                    response.close()
            except (requests.RequestException, ValueError, OSError):
                self.notify("Не удалось обновить привязанную сессию")
                return False
        self.token = None
        self.sessions.clear(self.account_id)
        self.notify("Сессия истекла. Войдите снова.")
        if interactive:
            self.login()
        return bool(self.token)

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _authorized_request(self, request, *, interactive=True):
        response = request()
        if response.status_code != 401:
            return response
        response.close()
        return request() if self._renew_session(interactive=interactive) else response

    def stream_chat(self, payload: dict) -> StreamResult:
        try:
            if validate_payload_images(payload):
                capability = self._authorized_request(lambda: self.transport.get(
                    f"{self.base_url}/capabilities", headers=self.headers,
                    timeout=10, allow_redirects=False), interactive=False)
                try:
                    if capability.status_code == 401:
                        return StreamResult(401, detail="Сессия истекла. Войдите снова; черновик сохранён")
                    if capability.status_code != 200 or capability.json().get("images") != IMAGE_PROTOCOL:
                        return StreamResult(400, detail="Сервер не поддерживает изображения; обновите сервер")
                finally:
                    capability.close()
        except (ValueError, TypeError, AttributeError):
            return StreamResult(400, detail="Некорректные изображения или возможности сервера")
        request = {**payload, "request_id": payload.get("request_id") or str(uuid4())}
        response = self._authorized_request(lambda: self.transport.post(
            f"{self.base_url}/chat/stream", json=request, headers=self.headers,
            stream=True, timeout=(10, 100), allow_redirects=False), interactive=False)
        if response.status_code == 200:
            return StreamResult(events=decode_sse(response), on_close=response.close,
                                on_cancel=lambda: interrupt_http(response))
        try:
            detail = response.json().get("detail", "Запрос отклонён сервером")
            return StreamResult(status_code=response.status_code, detail=str(detail)[:512])
        finally:
            response.close()

    def web_tool(self, kind: str, payload: dict) -> dict:
        if kind == "search":
            payload = {**payload, "request_id": payload.get("request_id") or str(uuid4())}
        try:
            response = self._authorized_request(lambda: self.transport.post(
                f"{self.base_url}/tools/web/{kind}", json=payload, headers=self.headers,
                timeout=25, allow_redirects=False), interactive=False)
            with response:
                if response.status_code == 401:
                    return failure("auth_required", "Сессия истекла. Войдите снова")
                if response.status_code != 200:
                    return failure("network", "Веб-инструмент недоступен")
                result = response.json()
                if not isinstance(result, dict) or result.get("status") not in {"ok", "error"}:
                    return failure("invalid_response", "Некорректный ответ веб-инструмента")
                return result
        except (requests.RequestException, ValueError):
            return failure("network", "Сетевая ошибка веб-инструмента; автоматического повтора нет")

    def _history_request(self, path, payload=None):
        method = self.transport.get if payload is None else self.transport.post
        arguments = {} if payload is None else {"json": payload}
        response = self._authorized_request(lambda: method(
            f"{self.base_url}{path}", headers=self.headers, timeout=(10, 100),
            allow_redirects=False, **arguments), interactive=False)
        try:
            if response.status_code == 404:
                raise LookupError("Чат не найден или сервер не поддерживает историю S4")
            if response.status_code != 200:
                raise ValueError(f"Операция с историей отклонена ({response.status_code})")
            return response.json()
        finally:
            response.close()

    def get_history(self, chat_id):
        from uuid import UUID
        return self._history_request(f"/chats/{UUID(str(chat_id))}/history")

    def context_info(self, payload):
        return self._history_request("/chat/context", payload)

    def fork_chat(self, chat_id, title, boundary_id=None):
        from uuid import UUID
        return self._history_request(f"/chats/{UUID(str(chat_id))}/fork",
                                     {"title": title, "boundary_id": boundary_id})

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

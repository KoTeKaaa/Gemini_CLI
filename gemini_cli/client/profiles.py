"""Приватные профили: токен никогда не выбирается по одному лишь наличию файла."""

import hashlib
import ipaddress
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit


def canonical_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise ValueError("Некорректный origin сервера")
    host = parsed.hostname.lower().encode("idna").decode("ascii")
    try:
        address = ipaddress.ip_address(host)
        host = address.compressed
        loopback = address.is_loopback
        if address.version == 6:
            host = "[" + host + "]"
    except ValueError:
        loopback = host == "localhost"
    if parsed.scheme == "http" and not loopback:
        raise ValueError("Удалённый сервер требует HTTPS")
    port = parsed.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Некорректный порт")
    suffix = "" if port is None or port == {"http": 80, "https": 443}[parsed.scheme] else f":{port}"
    return f"{parsed.scheme}://{host}{suffix}"


def private_json(path: Path, values: dict):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix":
        path.parent.chmod(0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = file.name
            json.dump(values, file, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


class RemoteSessions:
    def __init__(self, root: Path, origin: str):
        self.root = root
        self.origin = canonical_origin(origin)
        digest = hashlib.sha256(self.origin.encode()).hexdigest()
        self.directory = root / "remote" / digest
        self.pointer = self.directory / "active.json"

    @property
    def token_path(self):
        account = read_json(self.pointer).get("account_id")
        if not isinstance(account, str) or not account:
            return None
        return self.directory / (hashlib.sha256(account.encode()).hexdigest() + ".json")

    def load(self) -> dict:
        path = self.token_path
        data = read_json(path) if path else {}
        account = read_json(self.pointer).get("account_id")
        if (not isinstance(data.get("user"), dict)
                or data.get("_binding") != {"origin": self.origin, "account_id": account}
                or (data.get("user") or {}).get("id") != account):
            return {}
        return data

    def save(self, data: dict, *, expected_account=None):
        account = data["user"].get("id") if isinstance(data.get("user"), dict) else None
        if not isinstance(account, str) or not account or (expected_account and account != expected_account):
            raise ValueError("Сервер не подтвердил привязку аккаунта")
        if not data.get("access_token") or not data.get("refresh_token"):
            raise ValueError("Сервер не вернул сессию")
        for directory in (self.root, self.root / "remote", self.directory):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name == "posix":
                directory.chmod(0o700)
        path = self.directory / (hashlib.sha256(account.encode()).hexdigest() + ".json")
        private_json(path, {**data, "_binding": {"origin": self.origin, "account_id": account}})
        private_json(self.pointer, {"account_id": account})

    def clear(self):
        path = self.token_path
        if path:
            path.unlink(missing_ok=True)
        self.pointer.unlink(missing_ok=True)

    def migrate(self, legacy: Path):
        data = read_json(legacy)
        account = data["user"].get("id") if isinstance(data.get("user"), dict) else None
        if account and data.get("_binding") == {"origin": self.origin, "account_id": account}:
            self.save(data)

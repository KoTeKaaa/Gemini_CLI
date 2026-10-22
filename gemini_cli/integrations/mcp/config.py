"""Явные подключения из приватного каталога CLI; загрузка ничего не запускает."""

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

MAX_CONFIG_BYTES = 32768
NAME = re.compile(r"[a-z][a-z0-9_]{0,23}\Z")


@dataclass(frozen=True)
class Connection:
    name: str
    transport: str
    command: str = ""
    args: tuple[str, ...] = ()
    url: str = ""
    env_keys: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    auth: str = "none"
    enabled: bool = False
    timeout: int = 30
    # Plain HTTP/private addresses require this explicit per-connection choice.
    allow_private: bool = False


def validate_url(value: str, allow_private: bool = False) -> str:
    from ...client.profiles import canonical_origin
    parsed = urlsplit(value)
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("MCP URL не должен содержать секреты, query или fragment")
    origin = canonical_origin(parsed._replace(path="", query="", fragment="").geturl())
    if parsed.scheme != "https" and not allow_private:
        raise ValueError("Для локального HTTP нужно явное allow_private")
    return origin + (parsed.path or "/")


def load_connections(root: Path) -> dict[str, Connection]:
    path = root / "mcp.json"
    if not path.exists():
        return {}
    if path.is_symlink() or path.stat().st_size > MAX_CONFIG_BYTES:
        raise ValueError("MCP config: недопустимый файл или размер")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"version", "servers"} or data["version"] != 1:
        raise ValueError("MCP config: ожидается version=1 и servers")
    rows = data["servers"]
    if not isinstance(rows, list) or len(rows) > 8:
        raise ValueError("MCP config: не более восьми подключений")
    result = {}
    allowed = set(Connection.__dataclass_fields__)
    for row in rows:
        if not isinstance(row, dict) or set(row) - allowed:
            raise ValueError("MCP config: неизвестные поля; секреты храните отдельно")
        name = row.get("name")
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in result:
            raise ValueError("MCP config: неверное или повторное имя")
        for key in ("enabled", "allow_private"):
            if key in row and type(row[key]) is not bool:
                raise ValueError("MCP config: ожидается boolean")
        if type(row.get("timeout", 30)) is not int or not 1 <= row.get("timeout", 30) <= 120:
            raise ValueError("MCP config: timeout от 1 до 120 секунд")
        for key in ("args", "env_keys", "tools"):
            values = row.get(key, [])
            if (not isinstance(values, list) or len(values) > 32 or
                    any(not isinstance(v, str) or len(v) > 2048 or '\x00' in v for v in values)):
                raise ValueError("MCP config: неверный список аргументов/имён env")
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", key) for key in row.get("env_keys", [])):
            raise ValueError("MCP config: неверное имя env")
        transport = row.get("transport")
        if row.get("auth", "none") not in {"none", "bearer", "oauth"}:
            raise ValueError("MCP config: неизвестный способ авторизации")
        if transport == "stdio":
            if (not isinstance(row.get("command"), str) or not row["command"] or
                    len(row["command"]) > 2048 or row.get("url") or row.get("auth", "none") != "none"):
                raise ValueError("MCP config: stdio требует command без URL/auth")
        elif transport == "http":
            if row.get("command") or row.get("args") or row.get("env_keys") or not isinstance(row.get("url"), str):
                raise ValueError("MCP config: HTTP требует только URL")
            validate_url(row["url"], row.get("allow_private", False))
        else:
            raise ValueError("MCP config: transport stdio или http")
        result[name] = Connection(**{**row, "args": tuple(row.get("args", [])),
                                     "env_keys": tuple(row.get("env_keys", [])), "tools": tuple(row.get("tools", []))})
    return result

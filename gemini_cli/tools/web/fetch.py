"""Проверка публичных URL; транспорт использует только проверенные IP."""

from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class Target:
    url: str
    scheme: str
    host: str
    port: int
    path: str
    addresses: tuple


def public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        return (address.is_global and not address.is_multicast and not address.is_reserved
                and not address.is_unspecified and not address.is_loopback
                and not address.is_link_local and "%" not in value
                and not (isinstance(address, ipaddress.IPv6Address)
                         and (address.ipv4_mapped or address.sixtofour or address.teredo)))
    except ValueError:
        return False


def validate_target(url: str, *, resolver=socket.getaddrinfo) -> Target:
    if (not isinstance(url, str) or len(url) > 2048 or "\\" in url
            or any(ord(character) <= 32 or ord(character) == 127 for character in url)):
        raise ValueError("Некорректный URL")
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError()
        if parts.username is not None or parts.password is not None or "%" in parts.hostname:
            raise ValueError()
        host = parts.hostname.encode("idna").decode("ascii")
        port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise ValueError()
        path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
        path.encode("ascii")
    except (ValueError, UnicodeError):
        raise ValueError("Допустим публичный HTTP(S) URL без credentials") from None
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal:
        family = socket.AF_INET6 if literal.version == 6 else socket.AF_INET
        addresses = ((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                      (host, port, 0, 0) if literal.version == 6 else (host, port)),)
    else:
        try:
            addresses = tuple(resolver(host, port, type=socket.SOCK_STREAM))
        except OSError:
            raise ValueError("Не удалось разрешить публичный адрес") from None
    if not addresses or any(item[0] not in (socket.AF_INET, socket.AF_INET6)
                            or not public_address(item[4][0]) for item in addresses):
        raise ValueError("URL содержит запрещённый адрес назначения")
    return Target(urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, "")),
                  parts.scheme, host, port, path, addresses)

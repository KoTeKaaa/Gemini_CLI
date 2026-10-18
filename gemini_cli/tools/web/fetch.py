"""Проверка публичных URL; транспорт использует только проверенные IP."""

from dataclasses import dataclass
import ipaddress
import socket
import http.client
import ssl
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from threading import BoundedSemaphore, Timer
from urllib.parse import urljoin
from urllib.parse import urlsplit, urlunsplit
from .settings import WEB_TIMEOUT_SECONDS, WEB_MAX_BYTES, WEB_MAX_REDIRECTS


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


_DNS_POOL = ThreadPoolExecutor(max_workers=4)
_DNS_SLOTS = BoundedSemaphore(4)


def timed_resolver(deadline):
    def resolve(*args, **kwargs):
        if not _DNS_SLOTS.acquire(blocking=False):
            raise ValueError("DNS временно занят")
        future = _DNS_POOL.submit(socket.getaddrinfo, *args, **kwargs)
        future.add_done_callback(lambda _future: _DNS_SLOTS.release())
        try:
            return future.result(timeout=max(0.01, deadline - time.monotonic()))
        except FutureTimeout:
            future.cancel()
            raise ValueError("Превышено время DNS") from None
    return resolve


class PinnedConnection(http.client.HTTPConnection):
    def __init__(self, target, deadline):
        super().__init__(target.host, target.port, timeout=5)
        self.target, self.deadline = target, deadline

    def connect(self):
        for family, socktype, proto, _, address in self.target.addresses:
            self.sock = socket.socket(family, socktype, proto)
            try:
                self.sock.settimeout(max(0.01, min(5, self.deadline - time.monotonic())))
                self.sock.connect(address)
                if self.target.scheme == "https":
                    self.sock = ssl.create_default_context().wrap_socket(
                        self.sock, server_hostname=self.target.host)
                return
            except OSError:
                self.sock.close()
                if time.monotonic() >= self.deadline:
                    break
        raise ValueError("Не удалось установить проверенное соединение")

    def expire(self):
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.close()


@dataclass(frozen=True)
class FetchedPage:
    url: str
    final_url: str
    body: bytes
    content_type: str


def fetch_url(url: str, *, timeout=WEB_TIMEOUT_SECONDS, max_bytes=WEB_MAX_BYTES,
              redirects=WEB_MAX_REDIRECTS, resolver=None, connection_factory=PinnedConnection) -> FetchedPage:
    deadline = time.monotonic() + timeout
    resolver = resolver or timed_resolver(deadline)
    original = url
    for redirect in range(redirects + 1):
        if time.monotonic() >= deadline:
            raise ValueError("Превышено время загрузки")
        target = validate_target(url, resolver=resolver)
        connection = connection_factory(target, deadline)
        timer = Timer(max(0.01, deadline - time.monotonic()), connection.expire)
        timer.daemon = True
        timer.start()
        try:
            connection.request("GET", target.path, headers={
                "User-Agent": "GeminiCLI/1.0", "Accept-Encoding": "identity",
                "Accept": "text/html,text/plain,application/xhtml+xml"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location or redirect == redirects:
                    raise ValueError("Превышен предел перенаправлений")
                url = urljoin(target.url, location)
                continue
            if response.status != 200:
                raise ValueError("Страница недоступна")
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].lower().strip()
            if content_type not in {"text/html", "text/plain", "application/xhtml+xml"}:
                raise ValueError("Неподдерживаемый тип страницы")
            encoding = response.getheader("Content-Encoding", "identity").lower().strip()
            if encoding not in {"identity", "gzip", "deflate"}:
                raise ValueError("Неподдерживаемое сжатие")
            decoder = zlib.decompressobj(31 if encoding == "gzip" else 15) if encoding != "identity" else None
            body, received = bytearray(), 0
            while True:
                if time.monotonic() >= deadline:
                    raise ValueError("Превышено время загрузки")
                chunk = response.read1(min(65536, max_bytes - received + 1))
                if not chunk:
                    break
                received += len(chunk)
                if received > max_bytes:
                    raise ValueError("Страница слишком большая")
                body.extend(decoder.decompress(chunk, max_bytes - len(body) + 1) if decoder else chunk)
                if len(body) > max_bytes:
                    raise ValueError("Распакованная страница слишком большая")
            if decoder and (not decoder.eof or decoder.unused_data):
                raise ValueError("Некорректные сжатые данные")
            return FetchedPage(original, target.url, bytes(body), content_type)
        except (OSError, http.client.HTTPException, zlib.error):
            raise ValueError("Ошибка безопасной загрузки страницы") from None
        finally:
            timer.cancel()
            connection.close()
    raise ValueError("Превышен предел перенаправлений")

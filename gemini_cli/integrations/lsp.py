"""Последовательный JSON-RPC/LSP поверх ограниченного ManagedProcess."""
import json
import time
from pathlib import Path

from ..client.process import ManagedProcess


class LSPClient:
    def __init__(self, argv: list[str], root: str, *, cancelled=lambda: False, timeout=10):
        self.root = Path(root).resolve()
        self.cancelled, self.timeout = cancelled, timeout
        self.process = ManagedProcess(argv, str(self.root), limit=1048576)
        self.sequence, self.cursor = 0, 0
        self.buffer = b""
        self.notifications = []
        self.documents = {}

    def send(self, method: str, params=None, *, request_id=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if request_id is not None:
            message["id"] = request_id
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        self.process.write(f"Content-Length: {len(body)}\r\n\r\n" + body.decode("utf-8"))

    def receive(self):
        self.cursor, chunk = self.process.stdout.read_since(self.cursor)
        if chunk.startswith("[Начало вывода удалено]"):
            raise ValueError("Переполнен буфер LSP")
        self.buffer += chunk.encode("utf-8")
        if len(self.buffer) > 1048576:
            raise ValueError("Слишком большой ответ LSP")
        if b"\r\n\r\n" not in self.buffer:
            if len(self.buffer) > 8192:
                raise ValueError("Неверный заголовок LSP")
            return None
        header, body = self.buffer.split(b"\r\n\r\n", 1)
        fields = dict(line.split(b":", 1) for line in header.split(b"\r\n"))
        size = int(fields.get(b"Content-Length", b"-1").strip())
        if not 0 <= size <= 1048576:
            raise ValueError("Неверный размер LSP")
        if len(body) < size:
            return None
        self.buffer = body[size:]
        message = json.loads(body[:size])
        if not isinstance(message, dict):
            raise ValueError("Неверный ответ LSP")
        return message

    def request(self, method: str, params=None):
        self.sequence += 1
        request_id = self.sequence
        self.send(method, params, request_id=request_id)
        deadline = time.monotonic() + self.timeout
        while True:
            if self.cancelled() or time.monotonic() >= deadline:
                self.send("$/cancelRequest", {"id": request_id})
                raise InterruptedError("LSP отменён") if self.cancelled() else TimeoutError("Таймаут LSP")
            message = self.receive()
            if message is not None:
                if message.get("id") == request_id and "method" not in message:
                    if "error" in message:
                        raise ValueError("LSP сообщил об ошибке")
                    return message.get("result")
                if "method" in message:
                    if "id" in message:
                        # No workspace/configuration execution delegated to the server.
                        body = json.dumps({"jsonrpc": "2.0", "id": message["id"],
                                           "error": {"code": -32601, "message": "Unsupported request"}})
                        self.process.write(f"Content-Length: {len(body.encode())}\r\n\r\n{body}")
                    else:
                        self.notifications.append(message)
                        self.notifications = self.notifications[-100:]
                continue
            if self.process.poll() is not None:
                raise OSError("Процесс LSP завершён")
            time.sleep(.01)

    def initialize(self):
        result = self.request("initialize", {"processId": None, "rootUri": self.root.as_uri(),
            "capabilities": {"general": {"positionEncodings": ["utf-16"]}},
            "workspaceFolders": [{"uri": self.root.as_uri(), "name": self.root.name}]})
        if not isinstance(result, dict) or result.get("capabilities", {}).get("positionEncoding", "utf-16") != "utf-16":
            raise ValueError("Неподдерживаемая кодировка позиций LSP")
        self.send("initialized", {})
        return result

    def open_document(self, path: Path, text: str, version=1):
        uri = path.as_uri()
        if uri in self.documents and version <= self.documents[uri]:
            raise ValueError("Несовпадение версии документа")
        self.documents[uri] = version
        self.send("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": "python",
                                                           "version": version, "text": text}})

    def close(self):
        try:
            if self.process.poll() is None and not self.cancelled():
                old_timeout = self.timeout
                self.timeout = min(old_timeout, 1)
                self.request("shutdown")
                self.send("exit")
        except (OSError, ValueError, TimeoutError, InterruptedError):
            pass
        finally:
            self.process.close()

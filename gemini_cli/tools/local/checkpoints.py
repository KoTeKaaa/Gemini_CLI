"""Ограниченные приватные снимки вне workspace; содержимое не попадает в логи."""

import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from uuid import uuid4

from .changes import Change, MAX_BYTES
from .workspace import path_has_links


class CheckpointStore:
    def __init__(self, directory: Path, *, max_bytes=64 * 1024 * 1024, max_age=7 * 86400):
        self.directory = directory
        self.max_bytes, self.max_age = max_bytes, max_age

    def _prepare(self, root: str) -> None:
        full = os.path.realpath(self.directory)
        try:
            inside = os.path.commonpath((os.path.realpath(root), full)) == os.path.realpath(root)
        except ValueError:  # Workspace and profile may be on different Windows drives.
            inside = False
        if inside:
            raise ValueError("Контрольные точки должны храниться вне workspace")
        if path_has_links(str(self.directory)):
            raise ValueError("Ссылки в хранилище контрольных точек запрещены")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            self.directory.chmod(0o700)

    def cleanup(self, *, reserve=0) -> None:
        files = sorted((p for p in self.directory.glob("*.json") if p.is_file() and not p.is_symlink()),
                       key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for path in files:
            if time.time() - path.stat().st_mtime <= self.max_age and total + reserve <= self.max_bytes:
                continue
            total -= path.stat().st_size
            path.unlink()
        if total + reserve > self.max_bytes:
            raise OSError("Недостаточно места для контрольной точки")

    def save(self, change: Change, root: str) -> str:
        self._prepare(root)
        before = change.before
        payload = {"path": before.path, "mode": before.mode,
                   "data": None if before.data is None else base64.b64encode(before.data).decode("ascii"),
                   "fingerprint": before.fingerprint,
                   "proposed": hashlib.sha256(change.target).hexdigest()}
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        envelope = json.dumps({"payload": payload, "sha256": hashlib.sha256(raw).hexdigest()},
                              ensure_ascii=False).encode("utf-8")
        if len(envelope) > self.max_bytes:
            raise OSError("Контрольная точка превышает ограничение объёма")
        self.cleanup(reserve=len(envelope))
        key = uuid4().hex
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as stream:
                temporary = stream.name
                stream.write(envelope)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / (key + ".json"))
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        return key

    def load(self, change: Change) -> bytes | None:
        key = change.checkpoint
        if not isinstance(key, str) or len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("Контрольная точка отсутствует")
        path = self.directory / (key + ".json")
        if (path_has_links(str(path))
                or path.stat().st_size > 2 * MAX_BYTES
                or time.time() - path.stat().st_mtime > self.max_age):
            raise ValueError("Контрольная точка повреждена")
        try:
            envelope = json.loads(path.read_bytes())
            payload = envelope["payload"]
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            data = None if payload["data"] is None else base64.b64decode(payload["data"], validate=True)
            if (hashlib.sha256(raw).hexdigest() != envelope["sha256"]
                    or payload["path"] != change.before.path or payload["mode"] != change.before.mode
                    or payload["fingerprint"] != change.before.fingerprint or data != change.before.data
                    or payload["proposed"] != hashlib.sha256(change.target).hexdigest()):
                raise ValueError("Контрольная точка повреждена")
            return data
        except (KeyError, TypeError, UnicodeError, ValueError) as error:
            raise ValueError("Контрольная точка повреждена") from error

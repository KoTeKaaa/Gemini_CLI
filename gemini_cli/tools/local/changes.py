"""Снимки и журнал файловых операций одного хода; не использует Git."""

from dataclasses import dataclass
import difflib
import hashlib
import os
import stat

from .workspace import file_identity, is_sensitive_read_path, read_binary_snapshot, plan_text_file, resolve_safe_path

MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Snapshot:
    path: str
    data: bytes | None
    mode: int | None
    identity: tuple | None

    @property
    def fingerprint(self) -> str:
        return "missing" if self.data is None else hashlib.sha256(self.data).hexdigest()


def snapshot(root: str, path: str) -> Snapshot:
    full = resolve_safe_path(root, path)
    if (full is None or is_sensitive_read_path(full)
            or any(part in {".git", ".ssh", ".gnupg"} for part in os.path.relpath(full, root).split(os.sep))):
        raise ValueError("Доступ к файлу запрещён")
    # Reject aliases: a checkpoint must refer to the exact reviewed path.
    if os.path.abspath(os.path.join(root, path)) != full:
        raise ValueError("Ссылки в пути записи запрещены")
    try:
        expected = plan_text_file(root, path)
    except FileNotFoundError:
        if os.path.lexists(full):
            raise ValueError("Неподдерживаемый путь файла")
        return Snapshot(full, None, None, None)
    data = read_binary_snapshot(root, path, expected)
    if b"\x00" in data:
        raise ValueError("Бинарный файл пропущен")
    data.decode("utf-8")
    info = os.stat(full)
    if file_identity(info) != expected[1]:
        raise ValueError("Файл изменился во время чтения")
    return Snapshot(full, data, stat.S_IMODE(info.st_mode), expected[1])


@dataclass
class Change:
    before: Snapshot
    proposed: bytes
    actual: Snapshot | None = None
    status: str = "proposed"
    checkpoint: str | None = None

    def diff(self, *, proposed=False) -> str:
        after = self.proposed if proposed else (self.actual.data if self.actual else self.before.data)
        return "".join(difflib.unified_diff(
            (self.before.data or b"").decode("utf-8").splitlines(keepends=True),
            (after or b"").decode("utf-8").splitlines(keepends=True),
            fromfile="a/" + os.path.basename(self.before.path),
            tofile="b/" + os.path.basename(self.before.path)))


class ChangeSet:
    def __init__(self, root: str, turn_id: str = "", *, store=None):
        self.root = os.path.realpath(root)
        self.turn_id = turn_id
        self.entries: list[Change] = []
        self.store = store

    def propose(self, path: str, text: str) -> Change:
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES or "\x00" in text:
            raise ValueError("Нужен текст допустимого размера")
        change = Change(snapshot(self.root, path), text.encode("utf-8"))
        if len(self.entries) >= 64 or sum(len(e.proposed) + len(e.before.data or b"") for e in self.entries) + len(change.proposed) + len(change.before.data or b"") > 16 * MAX_BYTES:
            raise ValueError("Достигнут предел журнала правок за ход")
        self.entries.append(change)
        return change

    def validate(self, change: Change) -> None:
        if snapshot(self.root, change.before.path) != change.before:
            raise ValueError("Файл изменился после предпросмотра")

    def applied(self, change: Change) -> None:
        actual = snapshot(self.root, change.before.path)
        if actual.data != change.proposed:
            change.status = "conflict"
            raise ValueError("Записанная версия изменилась; требуется проверка")
        change.actual = actual
        change.status = "applied"

    def write(self, change: Change) -> None:
        from .files import atomic_write_text
        self.validate(change)
        if self.store is not None:
            change.checkpoint = self.store.save(change, self.root)
        atomic_write_text(change.before.path, change.proposed.decode("utf-8"), newline="",
                          validate=lambda: self.validate(change))
        self.applied(change)

    def summary(self) -> str:
        if not self.entries:
            return "В последнем ходе нет файловых правок."
        labels = {"proposed": "предложено", "applied": "применено", "denied": "отклонено",
                  "failed": "ошибка", "conflict": "конфликт", "undone": "отменено", "skipped": "пропущено"}
        return "\n".join(f"{index}. {os.path.relpath(item.before.path, self.root)}: "
                         f"{labels.get(item.status, item.status)}"
                         for index, item in enumerate(self.entries, 1))

"""Снимки и журнал файловых операций одного хода; не использует Git."""

from dataclasses import dataclass
import difflib
import hashlib
import os
import stat

from .workspace import is_sensitive_read_path, read_binary_snapshot, plan_text_file, resolve_safe_path, path_has_links

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
    root = os.path.realpath(root)
    full = resolve_safe_path(root, path)
    if (full is None or is_sensitive_read_path(full)
            or any(part in {".git", ".ssh", ".gnupg"} for part in os.path.relpath(full, root).split(os.sep))):
        raise ValueError("Доступ к файлу запрещён")
    # Reject aliases: a checkpoint must refer to the exact reviewed path.
    if path_has_links(os.path.join(root, path)):
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
    if plan_text_file(root, path) != expected:
        raise ValueError("Файл изменился во время чтения")
    return Snapshot(full, data, stat.S_IMODE(info.st_mode), expected[1])


@dataclass
class Change:
    before: Snapshot
    proposed: bytes
    actual: Snapshot | None = None
    status: str = "proposed"
    checkpoint: str | None = None
    selected: bytes | None = None

    @property
    def target(self) -> bytes:
        return self.proposed if self.selected is None else self.selected

    def diff(self, *, proposed=False) -> str:
        after = self.proposed if proposed else (self.actual.data if self.actual else self.before.data)
        name = "".join(c if c.isprintable() else "?" for c in os.path.basename(self.before.path))
        lines = difflib.unified_diff(
            (self.before.data or b"").decode("utf-8").splitlines(keepends=True),
            (after or b"").decode("utf-8").splitlines(keepends=True),
            fromfile="a/" + name, tofile="b/" + name)
        return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)


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
        total = sum(len(e.proposed) + len(e.before.data or b"") for e in self.entries)
        if len(self.entries) >= 64 or total + len(change.proposed) + len(change.before.data or b"") > 16 * MAX_BYTES:
            raise ValueError("Достигнут предел журнала правок за ход")
        self.entries.append(change)
        return change

    def validate(self, change: Change) -> None:
        if snapshot(self.root, change.before.path) != change.before:
            raise ValueError("Файл изменился после предпросмотра")

    def applied(self, change: Change) -> None:
        actual = snapshot(self.root, change.before.path)
        if actual.data != change.target:
            change.status = "conflict"
            raise ValueError("Записанная версия изменилась; требуется проверка")
        change.actual = actual
        change.status = "applied"

    def write(self, change: Change, *, cancelled=lambda: False) -> None:
        from .files import atomic_write_text
        def validate():
            if cancelled():
                raise InterruptedError("Ход отменён до записи файла")
            self.validate(change)
        validate()
        if self.store is not None:
            if change.checkpoint is None:
                change.checkpoint = self.store.save(change, self.root)
            else:
                self.store.load(change)
        atomic_write_text(change.before.path, change.target.decode("utf-8"), newline="",
                          validate=validate)
        self.applied(change)

    def summary(self) -> str:
        if not self.entries:
            return "В последнем ходе нет файловых правок."
        labels = {"proposed": "предложено", "applied": "применено", "denied": "отклонено",
                  "failed": "ошибка", "conflict": "конфликт", "undone": "отменено", "skipped": "пропущено"}
        def label(path):
            return "".join(c if c.isprintable() else "?" for c in os.path.relpath(path, self.root))
        return "\n".join(f"{index}. {label(item.before.path)}: "
                         f"{labels.get(item.status, item.status)}"
                         for index, item in enumerate(self.entries, 1))

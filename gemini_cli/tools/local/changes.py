"""Снимки файлов и ограниченный журнал ходов чата; не использует Git."""

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
    turn_id: str = ""

    @property
    def target(self) -> bytes:
        return self.proposed if self.selected is None else self.selected

    def diff(self, *, proposed=False) -> str:
        if self.status == "undone":
            return ""
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
        self._entries: list[Change] = []
        self.store = store

    @property
    def entries(self) -> list[Change]:
        return self._entries

    def propose(self, path: str, text: str) -> Change:
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES or "\x00" in text:
            raise ValueError("Нужен текст допустимого размера")
        change = Change(snapshot(self.root, path), text.encode("utf-8"), turn_id=self.turn_id)
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

    def active_files(self) -> dict[str, list[Change]]:
        groups = {}
        for item in self.entries:
            if item.status == "applied" and item.actual is not None:
                groups.setdefault(item.before.path, []).append(item)
        return {path: items for path, items in groups.items() if
                any(items[i].before != items[i - 1].actual for i in range(1, len(items)))
                or (items[0].before.data, items[0].before.mode) != (items[-1].actual.data, items[-1].actual.mode)}

    def resolve_path(self, path: str) -> str:
        full = resolve_safe_path(self.root, path)
        if full not in self.active_files():
            raise ValueError("Файл отсутствует в активных правках этого чата и рабочей папки")
        return full

    def file_diff(self, path: str) -> str:
        items = self.active_files().get(path)
        if not items:
            raise ValueError("Нет активных изменений этого файла")
        chains = [[items[0]]]
        for item in items[1:]:
            if item.before != chains[-1][-1].actual:
                chains.append([])
            chains[-1].append(item)
        pages = []
        for chain in chains:
            combined = Change(chain[0].before, chain[-1].actual.data, actual=chain[-1].actual, status="applied")
            diff = combined.diff()
            if not diff and chain[0].before.data is None:
                diff = "Создание пустого файла\n"
            if diff:
                pages.append(diff)
        separator = "\nРучное изменение между записями: отдельная цепочка правок агента\n\n"
        return separator.join(pages)

    def listing(self) -> str:
        groups = self.active_files()
        if not groups:
            return "Активных файловых правок нет."
        rows = []
        for index, (path, items) in enumerate(groups.items(), 1):
            label = "".join(c if c.isprintable() else "?" for c in os.path.relpath(path, self.root))
            operation = "создан" if items[0].before.data is None else "изменён"
            turns = len({item.turn_id for item in items})
            rows.append(f"#{index} — {label} · {operation} · ходов: {turns}")
        return "\n".join(rows) + "\n/diff путь — посмотреть · /undo путь — откатить файл"

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


class ChangeHistory(ChangeSet):
    """Изолированный журнал чата: до 32 ходов с правками и 64 МиБ снимков."""
    def __init__(self, root: str, *, store=None):
        super().__init__(root, store=store)
        self.turns: list[ChangeSet] = []

    @property
    def entries(self) -> list[Change]:
        return [item for turn in self.turns for item in turn.entries]

    def begin_turn(self, turn_id: str) -> ChangeSet:
        turn = ChangeSet(self.root, turn_id, store=self.store)
        self.turns.append(turn)
        return turn

    def trim(self) -> int:
        active = set(self.active_files())
        for turn in self.turns:
            turn._entries[:] = [item for item in turn.entries
                                if item.status == "applied" and item.before.path in active]
        self.turns = [turn for turn in self.turns if any(item.status == "applied" for item in turn.entries)]
        dropped = 0
        def size():
            return sum(len(item.before.data or b"") + len(item.proposed) +
                       len(item.actual.data or b"") for item in self.entries if item.actual is not None)
        while len(self.turns) > 32 or size() > 64 * 1024 * 1024:
            self.turns.pop(0)
            dropped += 1
        return dropped

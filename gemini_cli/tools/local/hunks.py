"""Выбор групп изменений по исходному снимку без fuzzy-применения patch."""

from dataclasses import dataclass
import difflib


@dataclass(frozen=True)
class Hunk:
    start: int
    end: int
    before: tuple[str, ...]
    after: tuple[str, ...]


def hunks(before: bytes, after: bytes) -> list[Hunk]:
    old = before.decode("utf-8").splitlines(keepends=True)
    new = after.decode("utf-8").splitlines(keepends=True)
    groups = difflib.SequenceMatcher(None, old, new).get_grouped_opcodes(3)
    return [Hunk(group[0][1], group[-1][2], tuple(old[group[0][1]:group[-1][2]]),
                 tuple(new[group[0][3]:group[-1][4]])) for group in groups]


def selected_version(before: bytes, selected: list[Hunk]) -> bytes:
    lines = before.decode("utf-8").splitlines(keepends=True)
    result, position, previous = [], 0, None
    for item in sorted(selected, key=lambda h: (h.start, h.end)):
        if (item.start < position or item.end < item.start or item.end > len(lines)
                or (previous is not None and item.start == previous.start)
                or tuple(lines[item.start:item.end]) != item.before):
            raise ValueError("Пересекающиеся или неприменимые фрагменты")
        result.extend(lines[position:item.start])
        result.extend(item.after)
        position, previous = item.end, item
    result.extend(lines[position:])
    return "".join(result).encode("utf-8")

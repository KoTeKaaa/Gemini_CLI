"""Подготовка единственной точной замены без изменения исходного файла."""

from dataclasses import dataclass
import difflib
import os

from .workspace import plan_text_file, read_text_snapshot
from .files import atomic_write_text
from ..results import failure, success


@dataclass(frozen=True)
class Replacement:
    root: str
    filepath: str
    expected: tuple
    original: str
    updated: str
    diff: str


def prepare_replacement(args: dict, current_dir: str, *, approve) -> Replacement:
    path, old, new = args.get("filepath"), args.get("old_text"), args.get("new_text")
    if (not isinstance(path, str) or not path or not isinstance(old, str) or not old
            or not isinstance(new, str)):
        raise ValueError("Нужны путь, непустой исходный и новый текст")
    root = os.path.realpath(current_dir)
    expected = plan_text_file(root, path)
    if not approve(f"Чтение {path!r} для подготовки точечной замены; содержимое будет обработано инструментом"):
        raise ValueError("Чтение для замены отклонено пользователем")
    original = read_text_snapshot(root, path, expected)
    index = original.find(old)
    if index < 0 or original.find(old, index + 1) >= 0:
        raise ValueError("Исходный фрагмент должен встречаться ровно один раз")
    if old == new:
        raise ValueError("Замена не изменяет файл")
    updated = original[:index] + new + original[index + len(old):]
    if len(updated.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("Результат превышает допустимый размер файла")
    relative = os.path.relpath(expected[0], root).replace(os.sep, "/")
    diff = "".join(difflib.unified_diff(original.splitlines(keepends=True), updated.splitlines(keepends=True),
                                     fromfile=f"a/{relative}", tofile=f"b/{relative}"))
    return Replacement(root, path, expected, original, updated, diff)


def apply_replacement(plan: Replacement) -> None:
    def validate():
        if read_text_snapshot(plan.root, plan.filepath, plan.expected) != plan.original:
            raise ValueError("Файл изменился после предпросмотра")
    validate()
    atomic_write_text(plan.expected[0], plan.updated, newline="", validate=validate)


def replace_in_file(args: dict, current_dir: str, *, approve, confirm_diff, changes=None,
                    cancelled=lambda: False) -> dict:
    item = None
    try:
        plan = prepare_replacement(args, current_dir, approve=approve)
        from .changes import ChangeSet
        changes = changes or ChangeSet(current_dir)
        item = changes.propose(plan.filepath, plan.updated)
        if item.before.data != plan.original.encode("utf-8") or item.before.identity != plan.expected[1]:
            raise ValueError("Файл изменился после предпросмотра")
        if not confirm_diff(plan.diff):
            item.status = "denied"
            return failure("denied", "Замена отклонена пользователем")
        if cancelled():
            item.status = "skipped"
            return failure("cancelled", "Ход отменён")
        changes.write(item)
        return success({"filepath": plan.filepath, "changed": True})
    except (EOFError, KeyboardInterrupt):
        if item is not None:
            item.status = "denied"
        return failure("denied", "Замена прервана пользователем")
    except ValueError as error:
        if item is not None:
            item.status = "failed"
        return failure("not_applied", str(error))
    except OSError:
        if item is not None:
            item.status = "failed"
        return failure("write_failed", "Не удалось применить замену; проверьте файл")

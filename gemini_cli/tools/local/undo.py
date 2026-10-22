"""Откат только проверенной цепочки записей агента; внешние действия не затрагивает."""

import os

from .changes import snapshot
from .files import atomic_write_text


def undo(changes, *, approve, selected_paths: list[str] | None = None,
         cancelled=lambda: False) -> list[dict]:
    groups = {}
    for item in changes.entries:
        if item.status == "applied":
            groups.setdefault(item.before.path, []).append(item)
    if not groups:
        return [{"filepath": "", "status": "Нет применённых файловых правок для отката"}]
    if selected_paths is not None:
        selected = set(selected_paths)
        if selected - groups.keys():
            raise ValueError("Выбранный файл отсутствует в применённых правках хода")
        groups = {path: items for path, items in groups.items() if path in selected}
        if not groups:
            return [{"filepath": "", "status": "Не выбраны файлы для отката"}]
    if not approve():
        return [{"filepath": "", "status": "Откат отклонён пользователем"}]
    results = []
    for path, items in groups.items():
        try:
            if cancelled():
                results.append({"filepath": path, "status": "Пропущено: отмена"})
                continue
            if changes.store is None:
                raise ValueError("Контрольная точка отсутствует")
            for index, item in enumerate(items):
                changes.store.load(item)
                if index and item.before != items[index - 1].actual:
                    raise ValueError("Ручное изменение между записями агента; откат запрещён")
            expected, before = items[-1].actual, items[0].before

            def validate():
                if snapshot(changes.root, path) != expected:
                    raise ValueError("Файл изменён после записи агента; откат запрещён")
            validate()
            if before.data is None:
                validate()
                os.unlink(path)
            else:
                atomic_write_text(path, before.data.decode("utf-8"), newline="", validate=validate)
            for item in items:
                item.status = "undone"
            results.append({"filepath": path, "status": "Восстановлено"})
        except (OSError, ValueError, UnicodeError):
            results.append({"filepath": path, "status": "Конфликт, отсутствующая или повреждённая точка; файл сохранён"})
        except (EOFError, KeyboardInterrupt):
            results.append({"filepath": path, "status": "Откат прерван; проверьте файл"})
            break
    return results

"""Подготовка и проверяемая запись набора; атомарность только одного файла."""

from contextlib import nullcontext
from .changes import ChangeSet


def write_set(files: list, changes: ChangeSet, *, approve, confirm_diff=None,
              notify=lambda _: None, cancelled=lambda: False, select=None, monitor=nullcontext) -> list[dict] | dict:
    if not isinstance(files, list) or not files or len(files) > 64:
        return {"error": "Нужен набор от 1 до 64 файлов"}
    plans, results, seen = [], [], set()
    for file in files:
        path = file.get("filepath", "") if isinstance(file, dict) else ""
        result = {"filepath": path, "status": "Ошибка: недоступный, секретный или неверный файл", "outcome": "failed"}
        results.append(result)
        try:
            if not isinstance(path, str) or not path or not isinstance(file.get("content"), str):
                raise ValueError("Нужны путь и текст")
            item = changes.propose(path, file["content"])
            if item.before.path in seen:
                item.status = "failed"
                for prior, result in plans:
                    prior.status = "failed"
                return {"error": "Повторный путь в наборе; запись отменена"}
            seen.add(item.before.path)
            plans.append((item, result))
        except (OSError, ValueError, UnicodeError):
            pass
    try:
        if not plans:
            return results
        if select is not None:
            select(changes, [p for p, _ in plans])
        if not approve([{"filepath": p.before.path, "content": p.proposed.decode("utf-8")} for p, _ in plans]):
            for item, _ in plans:
                item.status = "denied"
            return {"error": "Операция отклонена пользователем"}
        if confirm_diff is not None and not confirm_diff("\n".join(p.diff(proposed=True) for p, _ in plans)):
            for item, _ in plans:
                item.status = "denied"
            return {"error": "Операция отклонена пользователем"}
        with monitor():
            return _apply(changes, plans, results, notify=notify, cancelled=cancelled)
    except (EOFError, KeyboardInterrupt):
        for item, _ in plans:
            item.status = "denied"
        return {"error": "Операция отклонена пользователем"}
    except (OSError, ValueError, UnicodeError) as error:
        for item, result in plans:
            item.status = "failed"
            result["status"] = "Ошибка предварительной проверки: " + str(error)
        return results


def _apply(changes, plans, results, *, notify, cancelled):
    selected = [p for p, _ in plans if p.status != "skipped"]
    if not cancelled():
        # Check every selected version and checkpoint before the first write.
        for item in selected:
            changes.validate(item)
        if changes.store is not None:
            for item in selected:
                item.checkpoint = changes.store.save(item, changes.root)
            for item in selected:
                changes.store.load(item)
        for item in selected:
            changes.validate(item)
    for item, result in plans:
        path = item.before.path
        try:
            if cancelled() or item.status == "skipped":
                item.status = "skipped"
                status = "Пропущено: отмена или нет выбранных фрагментов"
            else:
                changes.write(item, cancelled=cancelled)
                status = "Успешно записан"
        except (EOFError, KeyboardInterrupt):
            item.status = "failed"
            status = "Прервано пользователем; проверьте /diff"
            cancelled = lambda: True
        except (ValueError, OSError, UnicodeError) as error:
            item.status = "failed"
            status = "Ошибка: " + str(error)
        result["status"] = status
        result["outcome"] = item.status
        notify(f"{path}: {status}")
    return results

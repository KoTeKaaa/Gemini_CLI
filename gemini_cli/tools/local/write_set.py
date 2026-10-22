"""Подготовка и проверяемая запись набора; атомарность только одного файла."""

from .changes import ChangeSet


def write_set(files: list, changes: ChangeSet, *, approve, confirm_diff=None,
              notify=lambda _: None, cancelled=lambda: False) -> list[dict] | dict:
    if not isinstance(files, list) or not files or len(files) > 64:
        return {"error": "Нужен набор от 1 до 64 файлов"}
    plans, results, seen = [], [], set()
    for file in files:
        path = file.get("filepath", "") if isinstance(file, dict) else ""
        try:
            if not isinstance(path, str) or not path or not isinstance(file.get("content"), str):
                raise ValueError("Нужны путь и текст")
            item = changes.propose(path, file["content"])
            if item.before.path in seen:
                item.status = "failed"
                raise ValueError("Повторный путь в наборе")
            seen.add(item.before.path)
            plans.append(item)
        except (OSError, ValueError, UnicodeError):
            results.append({"filepath": path, "status": "Ошибка: недоступный, секретный или неверный файл"})
    try:
        if not plans:
            return results
        if not approve([{"filepath": p.before.path, "content": p.proposed.decode("utf-8")} for p in plans]):
            for item in plans:
                item.status = "denied"
            return {"error": "Операция отклонена пользователем"}
        if confirm_diff is not None and not confirm_diff("\n".join(p.diff(proposed=True) for p in plans)):
            for item in plans:
                item.status = "denied"
            return {"error": "Операция отклонена пользователем"}
    except (EOFError, KeyboardInterrupt):
        for item in plans:
            item.status = "denied"
        return {"error": "Операция отклонена пользователем"}
    for item in plans:
        path = item.before.path
        try:
            if cancelled():
                item.status = "skipped"
                status = "Пропущено: ход отменён"
            else:
                changes.write(item)
                status = "Успешно записан"
        except (ValueError, OSError, UnicodeError) as error:
            item.status = "failed"
            status = "Ошибка: " + str(error)
        results.append({"filepath": path, "status": status})
        notify(f"{path}: {status}")
    return results

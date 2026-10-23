"""Запуск локальной команды после явного подтверждения."""

import json
from contextlib import nullcontext
import logging
from ...client.process import ManagedProcess
from typing import Callable


def execute_command(
    args: dict, current_dir: str, *, approve: Callable[[str], bool],
    notify: Callable[[str], None], logger: logging.Logger,
    cancelled=lambda: False, on_process=None, monitor=nullcontext,
    argv=None, preflight=lambda: None,
) -> str:
    command = args.get("command", "").strip()
    if not command:
        return json.dumps({"error": "Команда пустая"})
    if not approve(command):
        return "Выполнение команды отменено пользователем."

    if cancelled():
        return json.dumps({"status": "cancelled"})
    notify("[green]Запуск процесса...[/green]")
    process = None
    try:
        preflight()
        if cancelled():
            return json.dumps({"status": "cancelled"})
        process = ManagedProcess(argv if argv is not None else command, current_dir)
        if on_process:
            on_process(process)
        with monitor():
            status = process.wait(timeout=120, cancelled=cancelled)
        return json.dumps({"status": status, "exit_code": process.poll(),
                           "stdout": process.stdout.read(), "stderr": process.stderr.read()},
                          ensure_ascii=False)
    except ValueError:
        return json.dumps({"status": "conflict", "error": "Файл изменился после просмотра; команда не запущена"}, ensure_ascii=False)
    except Exception:
        logger.exception("Ошибка запуска локальной команды")
        return json.dumps({"error": "Не удалось выполнить команду"})
    finally:
        if process is not None:
            process.close()

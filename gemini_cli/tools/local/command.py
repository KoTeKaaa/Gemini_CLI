"""Запуск локальной команды после явного подтверждения."""

import json
import logging
import subprocess
from typing import Callable


def execute_command(
    args: dict, current_dir: str, *, approve: Callable[[str], bool],
    notify: Callable[[str], None], logger: logging.Logger,
) -> str:
    command = args.get("command", "").strip()
    if not command:
        return json.dumps({"error": "Команда пустая"})
    if not approve(command):
        return "Выполнение команды отменено пользователем."

    notify("[green]Запуск процесса...[/green]")
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=current_dir,
            text=True,
            capture_output=True,
            timeout=120
        )

        response_data = {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
        return json.dumps(response_data, ensure_ascii=False)

    except subprocess.TimeoutExpired:
        notify("[red]❌ Превышено время ожидания (лимит 2 минуты)[/red]")
        return json.dumps({"error": "Превышено время ожидания выполнения команды (Timeout 120s)"})
    except Exception as e:
        logger.exception(f"Необработанное исключение: {e}")
        return json.dumps({"error": f"Критическая ошибка вызова подпроцесса: {str(e)}"})

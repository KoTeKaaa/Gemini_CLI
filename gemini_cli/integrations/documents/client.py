"""Документный worker в существующем ManagedProcess; байты живут только в памяти."""
import base64
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sys
import threading

from ...client.process import ManagedProcess
from ...tools.results import failure
from .boundary import MAX_BYTES


def extract_document(data: bytes, source: str, selection: dict, *, cancelled=lambda: False,
                     monitor=nullcontext, timeout=10, mime='') -> dict:
    if len(data) > MAX_BYTES or len(source) > 500 or len(json.dumps(selection)) > 2000:
        return failure('limit', 'Превышен предел запроса документа')
    if cancelled():
        return failure('cancelled', 'Чтение документа отменено')
    argv = ([sys.executable, '--document-worker'] if getattr(sys, 'frozen', False) else
            [sys.executable, '-B', '-m', 'gemini_cli.integrations.documents.worker'])
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'}
    # The controlled package must be imported from the application, never the workspace.
    root = str(Path(__file__).resolve().parents[3])
    process = None
    writer = None
    try:
        process = ManagedProcess(argv, root, env=env, memory_limit=512 * 1024 * 1024)
        request = json.dumps({'bytes': base64.b64encode(data).decode('ascii'), 'source': source,
                              'selection': selection, 'mime': mime}, ensure_ascii=False) + '\n'
        def send():
            try:
                process.write(request)
                process.process.stdin.close()
            except (OSError, ValueError):
                pass
        writer = threading.Thread(target=send, daemon=True)
        writer.start()
        with monitor():
            status = process.wait(timeout=timeout, cancelled=cancelled)
        if status != 'completed':
            return failure(status, 'Извлечение документа отменено или превышено время')
        if process.poll() != 0 or process.stdout.truncated:
            return failure('limit', 'Парсер превысил ресурсный предел или завершился с ошибкой')
        value = json.loads(process.stdout.read())
        if not isinstance(value, dict) or value.get('status') not in {'ok', 'error'}:
            raise ValueError()
        return value
    except (OSError, ValueError):
        return failure('parser_error', 'Не удалось выполнить локальный парсер')
    finally:
        if process is not None:
            process.close()
        if writer is not None:
            writer.join(1)

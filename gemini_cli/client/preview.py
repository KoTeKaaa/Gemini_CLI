"""Явный просмотр изображения через ОС; приватные файлы живут до удаления/выхода."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from threading import Thread
from uuid import uuid4


def open_external(path: Path) -> None:
    if sys.platform == 'win32':
        os.startfile(str(path))
        return
    executable = shutil.which('xdg-open')
    if not executable:
        raise ValueError('Не найден xdg-open. Установите xdg-utils и приложение просмотра изображений.')
    process = subprocess.Popen([executable, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if process.wait(timeout=1) != 0:
            raise ValueError('Система не смогла открыть изображение. Назначьте приложение просмотра PNG/JPEG/WebP.')
    except subprocess.TimeoutExpired:
        # Некоторые просмотрщики удерживают launcher до закрытия окна.
        # Не останавливаем пользовательское приложение при выходе из CLI.
        Thread(target=process.wait, daemon=True).start()


class ImagePreview:
    def __init__(self):
        self.directory = None
        self.paths: dict[str, Path] = {}

    def show(self, image) -> None:
        try:
            if self.directory is None:
                # Linux tmpfs не оставляет байты изображения на постоянном диске.
                ram = '/dev/shm' if sys.platform.startswith('linux') and os.access('/dev/shm', os.W_OK) else None
                self.directory = tempfile.TemporaryDirectory(prefix='gemini-preview-', dir=ram, ignore_cleanup_errors=True)
            path = self.paths.get(image.id)
            if path is None:
                suffix = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}[image.mime_type]
                path = Path(self.directory.name) / (uuid4().hex + suffix)
                self.paths[image.id] = path
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0)
                with os.fdopen(os.open(path, flags, 0o600), 'wb') as stream:
                    stream.write(image.data)
            open_external(path)
        except (OSError, ValueError):
            self.prune(set(self.paths) - {image.id})
            raise ValueError('Не удалось открыть изображение. Проверьте приложение просмотра и xdg-open на Linux.') from None

    def prune(self, keep: set[str]) -> None:
        for image_id, path in list(self.paths.items()):
            if image_id not in keep:
                try:
                    path.unlink(missing_ok=True)
                    del self.paths[image_id]
                except OSError:
                    pass  # Открытый Windows viewer может удерживать файл до завершения CLI.

    def close(self) -> str | None:
        self.prune(set())
        if self.directory is not None:
            path = Path(self.directory.name)
            self.directory.cleanup()
            self.directory = None
            if path.exists():
                return f'Просмотрщик удерживает временные файлы. Закройте его и удалите папку {path}'
        return None

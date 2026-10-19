"""Правка копии вложения в отдельном окне редактора, без изменения исходного файла."""

import os
from pathlib import Path
from contextlib import contextmanager
import shutil
import stat
import subprocess
import sys
import tempfile
from threading import Thread


def editor_command(path: Path) -> list[str]:
    if sys.platform == 'win32':
        return ['notepad.exe', str(path)]
    for name, options in [('gnome-text-editor', ['--standalone']),
                          ('gedit', ['--standalone', '--wait']),
                          ('code', ['--new-window', '--wait'])]:
        executable = shutil.which(name)
        if executable:
            return [executable, *options, str(path)]
    raise ValueError('Для отдельного окна установите GNOME Text Editor, gedit или VS Code. Черновик сохранён.')


_pending_cleanup: set[Path] = set()


@contextmanager
def working_copy(text: str):
    ram = '/dev/shm' if sys.platform.startswith('linux') and os.access('/dev/shm', os.W_OK) else None
    temporary = tempfile.TemporaryDirectory(prefix='gemini-edit-', dir=ram, ignore_cleanup_errors=True)
    root = Path(temporary.name)
    try:
        path = root / 'attachment.txt'
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0)
        with os.fdopen(os.open(path, flags, 0o600), 'wb') as stream:
            stream.write(text.encode('utf-8'))
        yield path
    finally:
        temporary.cleanup()
        if root.exists():
            _pending_cleanup.add(root)
            raise ValueError(f'Редактор удерживает временный файл: {root}. Закройте его; очистка повторится при выходе. Исходное вложение сохранено.')


def cleanup_pending() -> str | None:
    for root in list(_pending_cleanup):
        shutil.rmtree(root, ignore_errors=True)
        if not root.exists():
            _pending_cleanup.discard(root)
    if _pending_cleanup:
        return 'После закрытия редактора удалите временные папки: ' + ', '.join(map(str, _pending_cleanup))
    return None


def edit_external(text: str) -> str:
    try:
        with working_copy(text) as path:
            command = editor_command(path)
            if sys.platform == 'win32':
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    input('Сохраните и закройте документ в Блокноте, затем нажмите Enter здесь (Ctrl+C — отмена): ')
                    if process.poll() not in (None, 0):
                        raise ValueError('Блокнот не смог открыть документ. Исходное вложение сохранено.')
                finally:
                    if process.poll() is None:
                        Thread(target=process.wait, daemon=True).start()
            else:
                subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            flags = (os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
                     | getattr(os, 'O_NONBLOCK', 0))
            with os.fdopen(os.open(path, flags), 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError('Редактор должен сохранить обычный текстовый файл')
                data = stream.read(128 * 1024 + 1)
            if len(data) > 128 * 1024:
                raise ValueError('Изменённый текст слишком большой. Исходное вложение сохранено.')
            result = data.decode('utf-8')
        return result
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise ValueError('Не удалось получить текст из отдельного редактора. Исходное вложение сохранено.') from None

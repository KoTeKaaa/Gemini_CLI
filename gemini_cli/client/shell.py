"""Ручная оболочка наследует TTY; её команды не проходят через runner."""

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
from contextlib import contextmanager

from .shell_startup import shell_command


def select_shell(*, platform: str = os.name, environ=None) -> str:
    environ = os.environ if environ is None else environ
    candidates = (['pwsh', 'powershell'] if platform == 'nt'
                  else [environ.get('SHELL') or 'bash'])
    for candidate in candidates:
        executable = shutil.which(candidate)
        if executable:
            name = Path(executable).stem.lower()
            if name not in {'bash', 'zsh', 'pwsh', 'powershell'}:
                raise ValueError('Поддерживаются Bash, zsh и PowerShell.')
            return executable
    raise ValueError('Интерактивная оболочка не найдена.')


@contextmanager
def terminal_owner():
    """Ребёнок получает Ctrl+C, родитель восстанавливает настройки TTY."""
    saved = None
    if os.name != 'nt':
        import termios
        saved = termios.tcgetattr(sys.stdin.fileno())
    previous = signal.getsignal(signal.SIGINT)
    # Обработчик (в отличие от SIG_IGN) сбрасывается при exec в ребёнке.
    signal.signal(signal.SIGINT, lambda *_: None)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)
        if saved is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, saved)


def read_return_directory(path: Path) -> str | None:
    try:
        with path.open('rb') as stream:
            raw = stream.read(16385)
        if not raw:
            return None
        if len(raw) > 16384:
            raise ValueError
        directory = raw.decode('utf-8')
        if '\x00' in directory or not os.path.isabs(directory) or not os.path.isdir(directory):
            raise ValueError
        return os.path.realpath(directory)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError('Оболочка закрыта; каталог не передан или больше недоступен. Workspace сохранён.') from exc


def launch_shell(workspace: str, *, announce=print) -> str | None:
    """Возвращает каталог только после явного exit-to-cli --sync-dir."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError('/term требует интерактивного терминала (TTY).')
    executable = select_shell()
    if not os.path.isdir(workspace):
        raise ValueError('Рабочая папка больше недоступна.')
    announce(f'Оболочка: {executable}\nПапка: {workspace}\n'
             'Возврат: exit или exit-to-cli; перенос папки: exit-to-cli --sync-dir')
    with tempfile.TemporaryDirectory(prefix='gemini-shell-') as temporary:
        root = Path(temporary)
        returned = root / 'directory'
        command, environment = shell_command(executable, root, returned)
        try:
            with terminal_owner():
                result = subprocess.run(command, cwd=workspace, env=environment, check=False)
        except OSError as exc:
            raise ValueError('Не удалось запустить интерактивную оболочку.') from exc
        if result.returncode:
            announce(f'Оболочка завершилась с кодом {result.returncode}.')
        return read_return_directory(returned)

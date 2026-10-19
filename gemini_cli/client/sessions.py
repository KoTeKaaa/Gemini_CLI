"""Named in-process shells: detach keeps a process; CLI shutdown stops it."""
import atexit
import os
import re
from contextlib import contextmanager
from .process_windows import start_process


class SessionManager:
    def __init__(self, factory=start_process):
        self.sessions, self.factory = {}, factory
        atexit.register(self.close)

    def start(self, name, cwd):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", name):
            raise ValueError("Имя: 1–32 символа a-z, 0-9, _ или -")
        if name in self.sessions:
            raise ValueError("Сессия уже существует; используйте attach или stop")
        if len(self.sessions) >= 8:
            raise ValueError("Не более восьми сессий")
        command = ([os.environ.get("COMSPEC", "cmd.exe"), "/Q"] if os.name == "nt"
                   else [os.environ.get("SHELL", "/bin/sh"), "-i"])
        self.sessions[name] = self.factory(command, cwd, pty=True)
        return self.sessions[name]

    def get(self, name):
        if name not in self.sessions:
            raise ValueError("Сессия не найдена")
        return self.sessions[name]

    def list(self):
        return [(name, "running" if process.poll() is None else "exited")
                for name, process in self.sessions.items()]

    def stop(self, name):
        process = self.get(name)
        process.close()
        del self.sessions[name]

    def close(self):
        try:
            for name in list(self.sessions):
                self.stop(name)
        finally:
            atexit.unregister(self.close)


@contextmanager
def terminal_output(stream):
    if os.name != "posix":
        yield
        return
    import termios
    descriptor = stream.fileno()
    original = termios.tcgetattr(descriptor)
    raw = list(original)
    raw[1] &= ~termios.OPOST
    termios.tcsetattr(descriptor, termios.TCSANOW, raw)
    try:
        yield
    finally:
        termios.tcsetattr(descriptor, termios.TCSANOW, original)


def attach(process):
    # A terminal is not a formatted-text widget: relay VT/OSC output unchanged
    # so the host terminal handles cursor movement, zsh hooks and line editing.
    import sys
    import time
    from contextlib import closing
    from prompt_toolkit.input import create_input
    from prompt_toolkit.output import create_output
    from prompt_toolkit.keys import Keys

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("Подключение к сессии требует интерактивного терминала (TTY)")
    output = create_output(stdout=sys.stdout)
    position, previous_size = 0, None
    def write(text):
        output.write_raw(text)
        output.flush()
    with closing(create_input()) as source, source.raw_mode(), terminal_output(sys.stdout):
        write("\x1b[?1049h\x1b[2J\x1b[HCtrl+] — в чат; процесс продолжит работу\r\n")
        try:
            last_flush = time.monotonic()
            while True:
                size = output.get_size()
                if size != previous_size:
                    process.resize(size.rows, size.columns)
                    previous_size = size
                position, text = process.stdout.read_since(position)
                if text:
                    write(text)
                if process.poll() is not None:
                    # The reader may still be draining the last output chunk.
                    for reader in process._readers:
                        reader.join(.2)
                    _, text = process.stdout.read_since(position)
                    write(text)
                    return
                keys = source.read_keys()
                if time.monotonic() - last_flush >= .05:
                    keys += source.flush_keys()
                    last_flush = time.monotonic()
                for press in keys:
                    if press.key == Keys.ControlSquareClose:
                        return
                    text = press.data
                    if press.key == Keys.BracketedPaste:
                        text = "\x1b[200~" + text + "\x1b[201~"
                    if text:
                        process.write(text)
                if source.closed:
                    return
                time.sleep(.01)
        finally:
            # Restore host modes before giving input back to the chat.
            write("\x1b[?2004l\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l"
                  "\x1b[?1l\x1b[?25h\x1b[0m\x1b[r\x1b[?1049l")


def session_command(manager, text, cwd, notify):
    parts = text.split()
    if len(parts) == 1 or parts[1:] == ["list"]:
        notify("\n".join(f"{name}: {'работает' if status == 'running' else 'завершена'}"
                         for name, status in manager.list()) or
               "Сессий нет. Создать: /session start build. Имя build можно заменить своим.")
    elif len(parts) == 3 and parts[1] in {"start", "attach", "stop"}:
        action, name = parts[1:]
        if action == "stop":
            manager.stop(name)
            notify(f"Сессия {name} остановлена вместе с дочерними процессами.")
        else:
            process = manager.start(name, cwd) if action == "start" else manager.get(name)
            attach(process)
            notify(f"Сессия {name}: " + ("отсоединена; процесс продолжает работу. Вернуться: /session attach " + name
                                      if process.poll() is None else "завершена. Удалить из списка: /session stop " + name))
    else:
        notify("Создать оболочку: /session start build (build — любое имя).\n"
                         "Вернуться в неё: /session attach build. Остановить: /session stop build.\n"
                         "Список: /session. Ctrl+] — вернуться в чат, сохранив процесс.\n"
                         "При закрытии CLI все сессии останавливаются.")

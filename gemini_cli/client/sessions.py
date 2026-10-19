"""Named in-process shells: detach keeps a process; CLI shutdown stops it."""
import atexit
import os
import re
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


def attach(process):
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import ANSI
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    keys = KeyBindings()
    @keys.add("c-]")
    def detach(event):
        event.app.exit()
    @keys.add("<any>")
    def forward(event):
        if process.poll() is None:
            process.write(event.data)
    @keys.add("enter")
    def enter(event):
        if process.poll() is None:
            process.write("\r\n" if os.name == "nt" else "\n")
    def render():
        size = app.output.get_size()
        process.resize(size.rows, size.columns)
        status = "завершена" if process.poll() is not None else "работает"
        return ANSI(f"Ctrl+] — detach; сессия {status}\n" + process.stdout.read())
    app = Application(layout=Layout(Window(FormattedTextControl(render), wrap_lines=True)),
                      key_bindings=keys, full_screen=True, refresh_interval=.1)
    app.run()


def session_command(manager, text, cwd, notify):
    parts = text.split()
    if len(parts) == 1 or parts[1:] == ["list"]:
        notify("\n".join(f"{name}: {status}" for name, status in manager.list()) or "Сессий нет")
    elif len(parts) == 3 and parts[1] in {"start", "attach", "stop"}:
        action, name = parts[1:]
        if action == "stop":
            manager.stop(name)
        else:
            process = manager.start(name, cwd) if action == "start" else manager.get(name)
            attach(process)
    else:
        raise ValueError("/session [list | start NAME | attach NAME | stop NAME]; Ctrl+] — detach")

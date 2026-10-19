"""Transient work display: bounded logs, keyboard disclosure, no scrollback copy."""
from contextlib import contextmanager
from threading import RLock
from rich.live import Live
from rich.text import Text
from rich.console import Group
from rich.spinner import Spinner
from .process import ProcessLog
from .work_input import WorkInput


class WorkView:
    def __init__(self, console, state):
        self.console, self.state = console, state
        self.expanded, self.offset = False, 0
        self.process, self.text = None, ""
        self.archived = ProcessLog()
        self.lock = RLock()
        self.spinner = Spinner("dots", text="✨ Gemini думает...", style="green")

    def handle(self, key):
        with self.lock:
            if key == "f2":
                self.expanded = not self.expanded
                self.offset = 0
            elif key == "pageup":
                self.offset = min(65536, self.offset + 10)
            elif key == "pagedown":
                self.offset = max(0, self.offset - 10)

    def set_process(self, process):
        with self.lock:
            if self.process is not None:
                self.archived.append(self.process.stdout.read() + self.process.stderr.read())
            self.process = process

    def update_text(self, text):
        with self.lock:
            self.text = text

    def render(self):
        with self.lock:
            header = "Esc — отмена · F2 — вывод · PgUp/PgDn — прокрутка"
            if self.state is not None and self.state.cancelled.is_set():
                header += " · отменено"
            text = self.text
            if self.expanded:
                text = self.archived.read()
                if self.process is not None:
                    text += self.process.stdout.read() + self.process.stderr.read()
                text = text or "Вывода инструментов пока нет"
            steps = self.state.steps() if self.state is not None and self.expanded else []
            if steps:
                labels = {"queued": "ожидает", "running": "выполняется", "completed": "готово",
                          "failed": "ошибка", "cancelled": "отменено", "skipped": "пропущено"}
                header += "\n" + "\n".join(
                    f"{step['name']}: {labels.get(step['status'], step['status'])}" for step in steps)
            lines = text.splitlines()
            height = max(1, self.console.size.height - len(header.splitlines()) - 2)
            offset = min(self.offset, max(0, len(lines) - 1))
            end = len(lines) - offset
            return Text(header + "\n" + "\n".join(lines[max(0, end-height):end]))

    @contextmanager
    def screen(self):
        if self.console.is_terminal and not self.console.is_dumb_terminal:
            with Live(console=self.console, screen=False, refresh_per_second=10,
                      transient=True, get_renderable=lambda: Group(self.spinner, self.render())):
                yield
        else:
            yield

    @contextmanager
    def monitor(self):
        with WorkInput(self.state, self.handle), self.screen():
            yield

"""Подсказки без чтения содержимого и без обхода workspace."""

import os
from prompt_toolkit.completion import Completer, Completion
from ..tools.local.workspace import resolve_safe_path, is_sensitive_read_path, plan_text_file

COMMANDS = ('/help', '/model', '/settings', '/chat', '/delete', '/cd', '/paste',
            '/attachments', '/remove', '/paste-show', '/paste-edit', '/paste-remove')
SKIP = {'node_modules', 'build', 'dist', 'venv', '__pycache__'}


def allowed_path(root: str, relative: str) -> str | None:
    if any(part.startswith('.') or part in SKIP for part in relative.replace('\\', '/').split('/')):
        return None
    full = resolve_safe_path(root, relative)
    return full if full and not is_sensitive_read_path(full) else None


class InputCompleter(Completer):
    def __init__(self, root):
        self.root = root
        self.snapshots = {}

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith('/') and ' ' not in text:
            for command in COMMANDS:
                if command.startswith(text):
                    yield Completion(command, start_position=-len(text))
            return
        if not text.startswith('@') or '\n' in text:
            return
        fragment = text[1:]
        # Диапазон вводится после имени, список не читает файл для вычисления строк.
        if ':' in os.path.basename(fragment):
            return
        parent, prefix = os.path.split(fragment)
        directory = allowed_path(self.root(), parent) if parent else self.root()
        if directory is None:
            return
        try:
            with os.scandir(directory) as entries:
                for count, entry in enumerate(entries):
                    if count >= 2000:
                        break
                    relative = os.path.join(parent, entry.name)
                    if not entry.name.casefold().startswith(prefix.casefold()) or not allowed_path(self.root(), relative):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        yield Completion('@' + relative + os.sep, start_position=-len(text))
                    elif entry.is_file(follow_symlinks=False):
                        try:
                            expected = plan_text_file(self.root(), relative)
                        except (ValueError, OSError):
                            continue
                        self.snapshots[(self.root(), relative)] = expected
                        yield Completion('@' + relative, start_position=-len(text), display_meta=':1-20 — диапазон строк')
        except OSError:
            return

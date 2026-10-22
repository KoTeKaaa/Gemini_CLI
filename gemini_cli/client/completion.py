"""Подсказки без чтения содержимого и без обхода workspace."""

import os
from prompt_toolkit.completion import Completer, Completion
from ..tools.local.workspace import resolve_safe_path, is_sensitive_read_path, plan_text_file

COMMANDS = ('/help', '/model', '/chat', '/settings', '/term', '/paste',
            '/attachments', '/show', '/edit', '/remove', '/cd', '/delete', '/clear', '/compact', '/fork', '/limits', '/diff', '/undo', '/mcp')
SKIP = {'node_modules', 'build', 'dist', 'venv', '__pycache__'}


def allowed_path(root: str, relative: str) -> str | None:
    if any(part.startswith('.') or part in SKIP for part in relative.replace('\\', '/').split('/')):
        return None
    full = resolve_safe_path(root, relative)
    if not full or is_sensitive_read_path(full):
        return None
    canonical = os.path.relpath(full, os.path.realpath(root))
    if canonical != '.' and any(part.startswith('.') or part in SKIP for part in canonical.split(os.sep)):
        return None
    return full


class InputCompleter(Completer):
    def __init__(self, root, attachment_choices=lambda: (), mode=lambda: "remote", change_choices=lambda: ()):
        self.root = root
        self.attachment_choices = attachment_choices
        self.mode = mode
        self.change_choices = change_choices
        self.snapshots = {}

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        action, separator, fragment = text.partition(' ')
        if action in {'/diff', '/undo'} and separator:
            for path in self.change_choices():
                relative = os.path.relpath(path, os.path.realpath(self.root()))
                candidate, prefix = relative, fragment
                if os.name == "nt":
                    candidate, prefix = candidate.replace('\\', '/'), prefix.replace('\\', '/')
                if candidate.casefold().startswith(prefix.casefold()):
                    yield Completion(relative, start_position=-len(fragment), display_meta='Правки текущего чата')
            return
        if action in {'/remove', '/show', '/edit'} and separator:
            for number, description in self.attachment_choices():
                if str(number).startswith(fragment.removeprefix('#')):
                    yield Completion(str(number), start_position=-len(fragment), display_meta=description)
            return
        if text.startswith('/') and ' ' not in text:
            for command in COMMANDS:
                if command == '/limits' and self.mode() != 'remote':
                    continue
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
                        yield Completion('@' + relative, start_position=-len(text), display_meta='Файл целиком')
        except OSError:
            return

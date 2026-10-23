"""Подсказки без чтения содержимого и без обхода workspace."""

import os
from prompt_toolkit.completion import Completer, Completion
from ..tools.local.workspace import resolve_safe_path, is_sensitive_read_path, plan_text_file

COMMANDS = ('/help', '/model', '/chat', '/settings', '/term', '/paste',
            '/attachments', '/show', '/edit', '/remove', '/cd', '/delete', '/clear', '/compact', '/fork', '/limits', '/diff', '/undo', '/mcp', '/skill')
MCP_ACTIONS = ('check', 'tools', 'enable', 'disable', 'login', 'logout')
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
    def __init__(self, root, attachment_choices=lambda: (), mode=lambda: "remote", change_choices=lambda: (), mcp_choices=lambda: (), skill_choices=lambda: ()):
        self.root = root
        self.attachment_choices = attachment_choices
        self.mode = mode
        self.change_choices = change_choices
        self.mcp_choices = mcp_choices
        self.skill_choices = skill_choices
        self.snapshots = {}

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        action, separator, fragment = text.partition(' ')
        if action == '/skill' and separator:
            if '\n' in text:
                return
            words = text.split() + ([''] if text[-1].isspace() else [])
            choices = ('list', 'use', 'off') if len(words) == 2 else (
                sorted(self.skill_choices()) if len(words) == 3 and words[1] == 'use' else ())
            for choice in choices:
                if choice.startswith(words[-1]):
                    yield Completion(choice, start_position=-len(words[-1]), display_meta='Skills')
            return
        if action == '/mcp' and separator:
            if '\n' in text:
                return
            words = text.split()
            if text[-1].isspace():
                words.append('')
            choices = ()
            if len(words) == 2:
                choices = MCP_ACTIONS
            elif len(words) == 3 and words[1] in MCP_ACTIONS:
                choices = sorted(self.mcp_choices())
            elif len(words) == 4 and words[1] == 'login' and words[2] in self.mcp_choices():
                choices = ('memory', 'keyring')
            for choice in choices:
                if choice.casefold().startswith(words[-1].casefold()):
                    yield Completion(choice, start_position=-len(words[-1]), display_meta='MCP')
            return
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

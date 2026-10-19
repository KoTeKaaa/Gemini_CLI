"""Свёрнутые вставки сохраняют исходный текст отдельно от буфера ввода."""

from dataclasses import dataclass
from uuid import uuid4


@dataclass
class PasteBlock:
    token: str
    text: str

    @classmethod
    def create(cls, text: str):
        return cls(f'[Вставка {uuid4().hex[:8]}]', text)


def is_large(text: str) -> bool:
    return len(text) > 600 or text.count('\n') >= 6


def expand_blocks(text: str, blocks: list[PasteBlock]) -> str:
    # Однопроходная замена: вложенный похожий маркер не раскрывается рекурсивно.
    import re
    mapping = {block.token: block.text for block in blocks}
    if not mapping:
        return text
    return re.sub('|'.join(re.escape(token) for token in mapping), lambda match: mapping[match[0]], text)


def view_text(text: str) -> None:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.widgets import Frame, TextArea
    bindings = KeyBindings()
    @bindings.add('escape')
    @bindings.add('c-q')
    def close(event):
        event.app.exit()
    area = TextArea(text=text, read_only=True, scrollbar=True, wrap_lines=True)
    Application(layout=Layout(Frame(area, title='Вставка: Esc — закрыть')),
                key_bindings=bindings, full_screen=True).run()


def edit_text(text: str) -> str:
    from prompt_toolkit.shortcuts import prompt
    return prompt('Редактирование (Alt+Enter — готово): ', default=text, multiline=True)

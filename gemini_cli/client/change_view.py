"""Просмотр diff на временном экране без копирования содержимого в scrollback."""

import os

from prompt_toolkit.application import Application
from prompt_toolkit.filters import is_searching
from prompt_toolkit.search import start_search
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.widgets import Label, SearchToolbar, TextArea

from .input import safe_label


def change_pages(changes, *, proposed=False) -> list[tuple[str, str]]:
    pages = []
    for index, item in enumerate(changes.entries, 1):
        diff = item.diff(proposed=proposed)
        if not diff:
            continue
        path = safe_label(os.path.relpath(item.before.path, changes.root))
        kind = "предложено" if proposed else "фактически записано"
        pages.append((f"{index}. {path} · {kind} · {item.status}", diff))
    return pages


def diff_application(pages: list[tuple[str, str]], *, input=None, output=None):
    if not pages:
        raise ValueError("Нет diff для просмотра")
    position = [0]
    search = SearchToolbar()
    heading = Label("")
    body = TextArea(read_only=True, scrollbar=True, line_numbers=True,
                    wrap_lines=False, search_field=search)
    keys = KeyBindings()

    def show(index):
        position[0] = index % len(pages)
        title, text = pages[position[0]]
        heading.text = safe_label(title)
        body.text = text
        body.buffer.cursor_position = 0

    @keys.add("q", filter=~is_searching)
    @keys.add("escape", filter=~is_searching)
    def close(event):
        event.app.exit()

    @keys.add("n", filter=~is_searching)
    def next_file(event):
        show(position[0] + 1)

    @keys.add("p", filter=~is_searching)
    def previous_file(event):
        show(position[0] - 1)

    @keys.add("/", filter=~is_searching)
    def find(event):
        start_search(body.control)

    show(0)
    return Application(layout=Layout(HSplit([heading, body, search,
        Label("n/p — файл · ↑↓ PgUp/PgDn — прокрутка · / или Ctrl+F — поиск · Esc/q — назад")]),
        focused_element=body), key_bindings=keys, full_screen=True, input=input, output=output)


def browse_changes(changes, *, proposed=False):
    pages = change_pages(changes, proposed=proposed)
    if pages:
        diff_application(pages).run()

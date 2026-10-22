"""Просмотр diff на временном экране без копирования содержимого в scrollback."""

import os

from prompt_toolkit.application import Application
from prompt_toolkit.filters import is_searching
from prompt_toolkit.search import start_search
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.widgets import Label, SearchToolbar, TextArea
from prompt_toolkit.shortcuts import checkboxlist_dialog, yes_no_dialog

from ..tools.local.changes import Change
from ..tools.local.hunks import hunks, selected_version

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


def select_changes(changes, items, *, interactive=True):
    if not interactive:
        for item in items:
            item.status = "skipped"
        return
    choices, groups = [], {}
    for index, item in enumerate(items):
        groups[index] = hunks(item.before.data or b"", item.proposed)
        path = safe_label(os.path.relpath(item.before.path, changes.root))
        for number, hunk in enumerate(groups[index]):
            choices.append(((index, number), f"{path} · фрагмент {number + 1} · строки {hunk.start + 1}–{hunk.end}"))
        # Creating an empty file is a meaningful operation despite no text diff.
        if not groups[index] and item.before.data is None:
            choices.append(((index, -1), f"{path} · создать пустой файл"))
    pages = [(os.path.relpath(i.before.path, changes.root), i.diff(proposed=True) or "Создание пустого файла")
             for i in items]
    diff_application(pages).run()
    selected = checkboxlist_dialog(title="Выберите файлы и фрагменты",
        text="Пробел — выбор; Tab — кнопки. Пустой выбор ничего не записывает.",
        values=choices, default_values=[key for key, _ in choices], ok_text="Далее", cancel_text="Отмена").run()
    selected = set(selected or [])
    chosen = []
    for index, item in enumerate(items):
        edits = [h for number, h in enumerate(groups[index]) if (index, number) in selected]
        if not edits and (index, -1) not in selected:
            item.status = "skipped"
            continue
        item.selected = selected_version(item.before.data or b"", edits)
        chosen.append(item)
    if chosen:
        diff_application([(safe_label(os.path.relpath(i.before.path, changes.root)),
                           Change(i.before, i.target).diff(proposed=True) or "Создание пустого файла")
                          for i in chosen]).run()
        if not yes_no_dialog(title="Применение набора", text="Записать выбранные изменения? "
                             "При частичном сбое результат будет показан по каждому файлу.").run():
            for item in chosen:
                item.status = "skipped"

"""Просмотр diff на временном экране без копирования содержимого в scrollback."""

import os

from prompt_toolkit.application import Application, get_app
from prompt_toolkit.filters import is_searching
from prompt_toolkit.search import start_search
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.widgets import Button, CheckboxList, Dialog, Label, SearchToolbar, TextArea
from prompt_toolkit.shortcuts import checkboxlist_dialog, radiolist_dialog

from ..tools.local.changes import Change
from ..tools.local.hunks import hunks, selected_version

from .input import safe_label


def change_pages(changes, *, proposed=False) -> list[tuple[str, str]]:
    pages = []
    for index, item in enumerate(changes.entries, 1):
        diff = item.diff(proposed=proposed)
        if not diff and item.before.data is None and (proposed or item.actual is not None):
            diff = "Создание пустого файла\n"
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
    if not choices:
        for item in items:
            item.status = "skipped"
        return
    selected = [key for key, _ in choices]
    while True:
        selected = checkboxlist_dialog(title="Выберите файлы и фрагменты",
            text="Пробел — выбор; Tab — кнопки. Diff можно открыть на следующем экране. "
                 "Пустой выбор ничего не записывает.",
            values=choices, default_values=selected, ok_text="Далее", cancel_text="Отмена").run()
        selected = set(selected or [])
        chosen = []
        for index, item in enumerate(items):
            edits = [h for number, h in enumerate(groups[index]) if (index, number) in selected]
            if not edits and (index, -1) not in selected:
                item.status = "skipped"
                continue
            item.status = "proposed"
            item.selected = selected_version(item.before.data or b"", edits)
            chosen.append(item)
        if not chosen:
            return
        summary = "\n".join(
            f"{safe_label(os.path.relpath(i.before.path, changes.root))} · "
            f"{'создать' if i.before.data is None else 'изменить'}" for i in chosen)
        while True:
            action = radiolist_dialog(title="Применение изменений",
                text=summary + "\nЗапись выполняется после вашего подтверждения. "
                     "При частичном сбое результат будет показан по каждому файлу.",
                values=[("write", "Записать выбранное"), ("diff", "Посмотреть diff"),
                        ("select", "Изменить выбор"), ("cancel", "Отмена")],
                ok_text="Выбрать", cancel_text="Отмена").run()
            if action == "write":
                return
            if action == "diff":
                diff_application([(safe_label(os.path.relpath(i.before.path, changes.root)),
                                   Change(i.before, i.target).diff(proposed=True) or "Создание пустого файла")
                                  for i in chosen]).run()
                continue
            if action == "select":
                break
            for item in chosen:
                item.status = "skipped"
            return


def select_undo_files(changes, *, interactive=True) -> list[str]:
    """Выбор путей для отката; весь набор требует явной отметки."""
    if not interactive:
        return []
    files = {}
    for item in changes.entries:
        if item.status == "applied":
            files.setdefault(item.before.path, item)
    if not files:
        return []
    choices = []
    for path, item in files.items():
        operation = "удалить созданный файл" if item.before.data is None else "восстановить файл"
        choices.append((path, f"{safe_label(os.path.relpath(path, changes.root))} · {operation}"))
    file_list = CheckboxList(values=choices, default_values=[])
    keys = KeyBindings()

    @keys.add("tab")
    def next_control(event):
        event.app.layout.focus_next()

    @keys.add("s-tab")
    def previous_control(event):
        event.app.layout.focus_previous()

    @keys.add("escape")
    @keys.add("c-c")
    def cancel(event):
        event.app.exit(result=[])

    dialog = Dialog(title="Выберите файлы для отката",
        body=HSplit([Label("Пробел — выбор; Tab — кнопки; Esc — отмена. "
                          "После выбора потребуется подтверждение.", dont_extend_height=True), file_list], padding=1),
        buttons=[Button(text="Далее", handler=lambda: get_app().exit(result=list(file_list.current_values))),
                 Button(text="Все файлы", handler=lambda: get_app().exit(result=list(files))),
                 Button(text="Отмена", handler=lambda: get_app().exit(result=[]))],
        with_background=True)
    selected = Application(layout=Layout(dialog), key_bindings=keys, full_screen=True).run()
    return [path for path in files if path in (selected or [])]

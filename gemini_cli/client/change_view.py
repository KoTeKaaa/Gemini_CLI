"""Просмотр diff на временном экране без копирования содержимого в scrollback."""

import os

from prompt_toolkit.application import Application
from prompt_toolkit.filters import is_searching
from prompt_toolkit.search import start_search
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.widgets import Label, SearchToolbar, TextArea

from ..tools.local.undo import undo

from .input import result_panel, safe_label


def change_pages(changes, *, filepath=None) -> list[tuple[str, str]]:
    pages = []
    for path in changes.active_files():
        if filepath is not None and path != filepath:
            continue
        diff = changes.file_diff(path)
        if diff:
            pages.append((safe_label(os.path.relpath(path, changes.root)), diff))
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
        Label(("n/p — файл · " if len(pages) > 1 else "") +
              "↑↓ PgUp/PgDn — прокрутка · / или Ctrl+F — поиск · Esc/q — назад")]),
        focused_element=body), key_bindings=keys, full_screen=True, input=input, output=output)


def handle_change_command(text: str, changes, console) -> bool:
    parts = text.strip().split(maxsplit=1)
    if not parts or parts[0] not in {"/diff", "/undo"}:
        return False
    command = parts[0]
    if changes is None:
        console.print(result_panel("Файловых правок пока нет.", title="Файловые правки"))
        return True
    if len(parts) == 1:
        console.print(result_panel(changes.listing(), title="Файловые правки"))
        return True
    try:
        path = changes.resolve_path(parts[1])
        if command == "/diff":
            if not console.is_terminal:
                raise ValueError("Для просмотра diff нужен интерактивный терминал.")
            pages = change_pages(changes, filepath=path)
            if not pages:
                raise ValueError("Для этого файла нет активных правок.")
            diff_application(pages).run()
        else:
            results = undo(changes, selected_paths=[path], approve=lambda: True)
            message = "\n".join(
                f"{safe_label(os.path.relpath(result['filepath'], changes.root))}: {safe_label(result['status'])}"
                if result["filepath"] else safe_label(result["status"]) for result in results)
            console.print(result_panel(message, title="Результат отката"))
    except (ValueError, OSError) as error:
        console.print(result_panel(safe_label(str(error)), title="Файловые правки", error=True))
    except (EOFError, KeyboardInterrupt):
        console.print(result_panel("Действие отменено.", title="Файловые правки"))
    return True

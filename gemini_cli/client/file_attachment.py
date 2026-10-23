"""Выбор @file:1-20: проверка снимка, согласие, однократное чтение."""

import re
from pathlib import Path
from .completion import allowed_path
from ..tools.local.workspace import plan_text_file, read_binary_snapshot

TEXT_LIMIT = 24000


def attach_file(draft, selection: str, root: str, *, snapshots: dict, approve) -> int | None:
    raw = selection.removeprefix('@')
    document_path, _, document_selection = raw.partition('#')
    if Path(document_path).suffix.casefold() in {'.pdf', '.docx', '.xlsx', '.csv'}:
        from ..tools.local.document import attach_document
        return attach_document(draft, document_path, document_selection, root, snapshots=snapshots, approve=approve)
    match = re.fullmatch(r'(.+):(\d+)(?:-(\d+))?', raw)
    if not match and re.search(r'(\[[:\d-]+\]|\s+\d+-\d+)$', raw):
        raise ValueError('Диапазон указывается без скобок и пробела: @file:1-20')
    relative = match[1] if match else raw
    if Path(relative).suffix.casefold() in {'.pdf', '.docx', '.xlsx', '.csv'}:
        raise ValueError('Документ требует #диапазон: @file.pdf#pages=1-3; /doc help')
    start, end = (int(match[2]), int(match[3] or match[2])) if match else (None, None)
    if start is not None and not 1 <= start <= end:
        raise ValueError('Диапазон строк начинается с 1 и не может быть обратным')
    if not allowed_path(root, relative):
        raise ValueError('Доступ к файлу запрещён')
    try:
        expected = snapshots.get((root, relative)) or plan_text_file(root, relative)
        if plan_text_file(root, relative) != expected:
            raise ValueError('Файл изменился после выбора; выберите его повторно')
    except FileNotFoundError:
        raise ValueError(f'Файл {relative!r} не найден. Пример диапазона: @file:1-20') from None
    if not approve(f'Файл {relative!r}' + (f', строки {start}-{end}' if match else ', целиком')):
        return
    data = read_binary_snapshot(root, relative, expected)
    extension = Path(relative).suffix.casefold()
    if extension in {'.png', '.jpg', '.jpeg', '.webp'}:
        if match:
            raise ValueError('Изображение не имеет диапазона строк')
        image = draft.add_image(Path(relative).name, data)
        return draft.number_of(image)
    if b'\0' in data:
        raise ValueError('Бинарный файл не поддерживается')
    try:
        text = data.decode('utf-8')
    except UnicodeError:
        raise ValueError('Текстовый файл должен быть UTF-8') from None
    if match:
        lines = text.splitlines(keepends=True)
        if end > len(lines):
            raise ValueError('Диапазон выходит за конец файла')
        text = ''.join(lines[start - 1:end])
    if len(text.encode('utf-8')) > TEXT_LIMIT:
        raise ValueError('Текст больше 24000 байт. Выберите диапазон, например @file:1-20')
    name = f'{relative}:{start}-{end}' if match else relative
    return draft.add_text_file(name, text)

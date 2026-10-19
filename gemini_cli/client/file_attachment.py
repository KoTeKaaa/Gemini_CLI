"""Выбор @путь[:N-M]: проверка снимка, согласие, однократное чтение."""

import re
from pathlib import Path
from .completion import allowed_path
from ..tools.local.workspace import plan_text_file, read_binary_snapshot

TEXT_LIMIT = 24000


def attach_file(draft, selection: str, root: str, *, snapshots: dict, approve) -> None:
    raw = selection.removeprefix('@')
    match = re.fullmatch(r'(.+):(\d+)-(\d+)', raw)
    relative = match[1] if match else raw
    start, end = (int(match[2]), int(match[3])) if match else (None, None)
    if start is not None and not 1 <= start <= end:
        raise ValueError('Диапазон строк начинается с 1 и не может быть обратным')
    if not allowed_path(root, relative):
        raise ValueError('Доступ к файлу запрещён')
    expected = snapshots.get((root, relative)) or plan_text_file(root, relative)
    if plan_text_file(root, relative) != expected:
        raise ValueError('Файл изменился после выбора; выберите его повторно')
    if not approve(f'Файл {relative!r}' + (f', строки {start}-{end}' if match else ', целиком')):
        return
    data = read_binary_snapshot(root, relative, expected)
    extension = Path(relative).suffix.casefold()
    if extension in {'.png', '.jpg', '.jpeg', '.webp'}:
        if match:
            raise ValueError('Изображение не имеет диапазона строк')
        draft.add_image(Path(relative).name, data)
        return
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
        raise ValueError('Текст больше 24000 байт; выберите меньший диапазон')
    draft.add_text_file(relative, text)

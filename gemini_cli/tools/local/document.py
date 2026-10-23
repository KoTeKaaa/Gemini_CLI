"""Явное чтение диапазона документа: согласие и проверка снимка до/после worker."""
from contextlib import nullcontext
import os
from pathlib import Path
from urllib.parse import parse_qsl

from ...integrations.documents.boundary import MAX_BYTES, MIMES
from ...integrations.documents.client import extract_document
from .workspace import plan_text_file, read_binary_snapshot, path_has_links
from ..results import failure


def parse_selection(value: str) -> dict:
    if not isinstance(value, str) or not value or len(value) > 1000:
        raise ValueError('Нужен диапазон документа. Примеры: pages=1-3; paragraphs=2-5; sheet=Лист1&cells=A1:C10')
    items = parse_qsl(value, keep_blank_values=True, strict_parsing=True, max_num_fields=4)
    if len(dict(items)) != len(items) or any(not key or not content for key, content in items):
        raise ValueError('Повторный или пустой параметр диапазона')
    return dict(items)


def read_document(args: dict, root: str, *, approve, expected=None,
                  cancelled=lambda: False, monitor=nullcontext) -> dict:
    try:
        path = args.get('filepath')
        if (not isinstance(path, str) or not path or os.path.isabs(path)
                or any(part.startswith('.') for part in path.replace('\\', '/').split('/'))
                or Path(path).suffix.casefold() not in MIMES or path_has_links(os.path.join(root, path))):
            raise ValueError('Нужен относительный путь PDF/DOCX/CSV/XLSX без секретов и ссылок')
        selection = parse_selection(args.get('selection'))
        planned = plan_text_file(root, path, max_bytes=MAX_BYTES)
        if expected is not None and expected != planned:
            raise ValueError('Документ изменился после выбора; выберите его заново')
        if not approve(f'Документ {path!r}, выбор {selection!r}; только извлечённые фрагменты будут отправлены модели'):
            return failure('denied', 'Чтение документа отклонено')
        data = read_binary_snapshot(root, path, planned, max_bytes=MAX_BYTES)
        source = os.path.relpath(planned[0], os.path.realpath(root)).replace(os.sep, '/')
        result = extract_document(data, source, selection, cancelled=cancelled, monitor=monitor,
                                  mime=args.get('mime', ''))
        if cancelled():
            return failure('cancelled', 'Чтение документа отменено; результат не принят')
        if path_has_links(os.path.join(root, path)) or plan_text_file(root, path, max_bytes=MAX_BYTES) != planned:
            raise ValueError('Документ изменился во время чтения; результат не принят')
        return result
    except (OSError, ValueError, TypeError):
        return failure('document_error', 'Неверный диапазон/путь, превышен размер или документ изменился; /doc help')


def attach_document(draft, path: str, selection: str, root: str, *, snapshots, approve):
    result = read_document({'filepath': path, 'selection': selection}, root, approve=approve,
                           expected=snapshots.get((root, path)))
    if result.get('status') != 'ok':
        if result.get('error', {}).get('code') == 'denied': return None
        raise ValueError(result['error']['message'])
    import json
    text = json.dumps(result, ensure_ascii=False)
    return draft.add_text_file(path + '#' + selection, text)

"""Диагностика и WorkspaceEdit через существующие подтверждения и ChangeSet."""
import time
from contextlib import nullcontext

from .lsp_tools import uri_path, validate_versions
from .write_set import write_set
from ..results import success


def offset(text: str, position: dict) -> int:
    line, column = position['line'], position['character']
    lines = text.splitlines(keepends=True)
    if text.endswith(('\n', '\r')) or not lines:
        lines.append('')
    if (type(line) is not int or type(column) is not int or not 0 <= line < len(lines)
            or column < 0):
        raise ValueError('Неверная позиция')
    raw = lines[line].rstrip('\r\n').encode('utf-16-le')
    if column * 2 > len(raw):
        raise ValueError('Колонка вне строки')
    prefix = raw[:column * 2].decode('utf-16-le')
    return sum(len(value) for value in lines[:line]) + len(prefix)


def rename_files(edit: dict, root: str, docs: dict, *, versions=None) -> list[dict]:
    if not isinstance(edit, dict) or set(edit) - {'changes', 'documentChanges'}:
        raise ValueError('Неподдерживаемый WorkspaceEdit')
    if 'changes' in edit and 'documentChanges' in edit:
        raise ValueError('Смешанный WorkspaceEdit')
    entries = edit.get('documentChanges')
    if entries is None:
        changes = edit.get('changes', {})
        if not isinstance(changes, dict):
            raise ValueError('Неверный WorkspaceEdit')
        entries = [{'textDocument': {'uri': uri}, 'edits': edits} for uri, edits in changes.items()]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
        raise ValueError('Нужны изменения 1–64 файлов')
    files, seen, count = [], set(), 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'textDocument', 'edits'}:
            raise ValueError('File operations не поддерживаются')
        document = entry['textDocument']
        path = uri_path(document['uri'], root)
        version = 1 if versions is None else next((number for uri, number in versions.items()
                                                   if uri_path(uri, root) == path), None)
        if path in seen or path not in docs or document.get('version') not in (None, version):
            raise ValueError('Повторный, неизвестный или изменённый документ')
        seen.add(path)
        text = docs[path][1]
        edits = entry['edits']
        if not isinstance(edits, list) or not edits:
            raise ValueError('Нужны текстовые изменения')
        count += len(edits)
        if count > 1000:
            raise ValueError('Слишком много изменений')
        spans = []
        for item in edits:
            if set(item) != {'range', 'newText'} or not isinstance(item['newText'], str):
                raise ValueError('Неподдерживаемый edit')
            start, end = (offset(text, item['range'][key]) for key in ('start', 'end'))
            if end < start:
                raise ValueError('Обратный диапазон')
            spans.append((start, end, item['newText']))
        spans.sort(key=lambda row: (row[0], row[1]))
        if any(b[0] < a[1] or b[0] == a[0] for a, b in zip(spans, spans[1:])):
            raise ValueError('Перекрывающиеся изменения')
        for start, end, replacement in reversed(spans):
            text = text[:start] + replacement + text[end:]
        files.append({'filepath': path, 'content': text})
    return files


def advanced(client, action, params, args, root, docs, *, changes, approve,
             cancelled=lambda: False, monitor=None):
    if action == 'rename':
        name = args.get('new_name')
        if not isinstance(name, str) or not name.isidentifier() or len(name) > 200:
            raise ValueError('Нужно новое имя Python')
        if changes is None or approve is None:
            raise ValueError('Нет механизма записи')
        params['newName'] = name
        with (monitor or nullcontext)():
            edit = client.request('textDocument/rename', params)
        files = rename_files(edit, root, docs, versions=client.documents)
        validate_versions(root, docs)
        def confirm(selected):
            validate_versions(root, docs)
            accepted = approve(selected)
            validate_versions(root, docs)
            return accepted
        def preview(diff):
            validate_versions(root, docs)
            accepted = approve([{'filepath': 'Предпросмотр rename (diff)', 'content': diff}])
            validate_versions(root, docs)
            return accepted
        result = write_set(files, changes, approve=confirm, confirm_diff=preview, cancelled=cancelled,
                           monitor=monitor or nullcontext)
        if isinstance(result, dict) or any(row.get('outcome') != 'applied' for row in result):
            return {'status': 'error', 'error': {'code': 'not_applied',
                    'message': 'Rename применён не полностью; проверьте /diff'}, 'data': {'files': result}}
        return success({'files': result})
    uri = params['textDocument']['uri']
    # Process notifications while waiting for this document's diagnostics.
    deadline = time.monotonic() + client.timeout
    while time.monotonic() < deadline:
        if cancelled():
            raise InterruptedError()
        for notification in client.notifications:
            data = notification.get('params', {})
            if notification.get('method') == 'textDocument/publishDiagnostics' and data.get('uri') == uri:
                if data.get('version') not in (None, 1):
                    raise ValueError('Устаревшая диагностика')
                validate_versions(root, docs)
                values = data.get('diagnostics', [])
                if not isinstance(values, list):
                    raise ValueError('Неверная диагностика')
                rows = [{'range': d.get('range'), 'severity': d.get('severity'),
                         'message': str(d.get('message', ''))[:500]} for d in values[:100] if isinstance(d, dict)]
                return success({'diagnostics': rows, 'version': data.get('version'),
                                'saved_snapshot_checked': True}, truncated=len(values) > 100)
        message = client.receive()
        if message and 'method' in message and 'id' not in message:
            client.notifications.append(message)
            client.notifications = client.notifications[-100:]
        if client.process.poll() is not None:
            raise OSError('LSP завершён')
        time.sleep(.01)
    raise TimeoutError('Нет диагностики для документа')

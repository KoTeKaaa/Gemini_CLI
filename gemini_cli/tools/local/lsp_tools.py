"""LSP видит только сохранённые версии; ответы ограничены workspace."""
import hashlib
import os
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import urlsplit, unquote

from ...integrations.lsp import LSPClient
from .search import walk_files, WalkBudget
from .workspace import plan_text_file, read_text_snapshot, path_has_links
from ..results import failure, success


def uri_path(uri: str, root: str) -> str:
    root = os.path.realpath(root)
    parsed = urlsplit(uri)
    if parsed.scheme != "file" or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Нужен локальный file URI")
    path = unquote(parsed.path)
    if os.name == "nt" and len(path) > 2 and path[0] == '/' and path[2] == ':':
        path = path[1:]
    relative = os.path.relpath(path, root)
    expected = plan_text_file(root, relative)
    if path_has_links(path) or any(p.startswith('.') for p in Path(relative).parts):
        raise ValueError("Недопустимый путь LSP")
    return os.path.relpath(expected[0], root).replace(os.sep, '/')


def documents(root: str) -> dict:
    found, total = {}, 0
    budget = WalkBudget()
    for relative, path in walk_files(root, budget):
        if not relative.endswith('.py') or path_has_links(path):
            continue
        if len(found) >= 400:
            raise ValueError("Проект превышает предел 400 Python-файлов")
        expected = plan_text_file(root, relative, max_bytes=262144)
        text = read_text_snapshot(root, relative, expected, max_bytes=262144)
        total += len(text.encode('utf-8'))
        if total > 4 * 1024 * 1024:
            raise ValueError("Проект превышает 4 МиБ")
        found[relative] = (expected, text)
    if budget.truncated:
        raise ValueError("Обход проекта неполон")
    return found


def validate_versions(root: str, docs: dict):
    for relative, (expected, _) in docs.items():
        if path_has_links(os.path.join(root, relative)) or plan_text_file(root, relative) != expected:
            raise ValueError("Версия документа изменилась")


def locations(result, root: str, docs: dict, *, limit=100) -> dict:
    rows, rejected = [], 0
    values = result if isinstance(result, list) else [result] if result else []
    for row in values[:1000]:
        try:
            path = uri_path(row.get('uri', row.get('targetUri', '')), root)
            if path not in docs:
                raise ValueError("Нет снимка документа")
            span = row.get('range', row.get('targetSelectionRange'))
            position = span['start']
            if (type(position['line']) is not int or position['line'] < 0
                    or type(position['character']) is not int or position['character'] < 0):
                raise ValueError("Неверная позиция")
            rows.append({'path': path, 'line': position['line'] + 1,
                         'character': position['character'], 'range': span})
        except (ValueError, OSError, KeyError, TypeError, AttributeError):
            rejected += 1
        if len(rows) >= limit:
            break
    return success({'locations': rows, 'rejected': rejected, 'precision': 'LSP; saved files only'},
                   truncated=len(values) > len(rows) + rejected)


def python_lsp(args: dict, root: str, *, approve, cancelled=lambda: False,
               client_factory=LSPClient, changes=None, confirm_write=None, monitor=None) -> dict:
    server = os.environ.get('GEMINI_CLI_PYLSP', '')
    if not server or not os.path.isabs(server):
        return failure('unavailable', 'Задайте абсолютный путь GEMINI_CLI_PYLSP; доступен python_symbols/search_text')
    action = args.get('action')
    if action not in {'definition', 'references', 'diagnostics', 'rename'}:
        return failure('invalid_arguments', 'Ожидается definition/references/diagnostics/rename')
    if not approve(f"Запустить LSP {server} в доверенном workspace; он сможет читать проект и конфигурацию"):
        return failure('denied', 'Запуск LSP отклонён')
    client = None
    try:
        docs = documents(root)
        path = args.get('filepath')
        if path not in docs:
            raise ValueError("Нужен сохранённый Python-файл из workspace")
        expected, text = docs[path]
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        if (args.get('expected_sha256') or digest) != digest:
            raise ValueError("Несовпадение версии документа")
        line, character = args.get('line', 1), args.get('character', 0)
        lines = text.splitlines(keepends=True)
        if text.endswith(('\n', '\r')) or not lines:
            lines.append('')
        if (type(line) is not int or not 1 <= line <= len(lines) or type(character) is not int
                or not 0 <= character <= len(lines[line - 1].rstrip('\r\n').encode('utf-16-le')) // 2):
            raise ValueError("Неверная позиция UTF-16")
        client = client_factory([server], root, cancelled=cancelled)
        with (monitor or nullcontext)():
            client.initialize()
            client.open_document(Path(expected[0]), text)
        params = {'textDocument': {'uri': Path(expected[0]).as_uri()},
                  'position': {'line': line - 1, 'character': character}}
        if action == 'references':
            params['context'] = {'includeDeclaration': True}
        if action in {'diagnostics', 'rename'}:
            from .lsp_edits import advanced
            with (monitor or nullcontext)() if action == 'diagnostics' else nullcontext():
                return advanced(client, action, params, args, root, docs, changes=changes,
                                approve=confirm_write, cancelled=cancelled, monitor=monitor)
        with (monitor or nullcontext)():
            result = client.request('textDocument/' + action, params)
        validate_versions(root, docs)
        if cancelled():
            raise InterruptedError()
        return locations(result, root, docs)
    except InterruptedError:
        return failure('cancelled', 'LSP отменён')
    except TimeoutError:
        return failure('timeout', 'Таймаут LSP; доступен обычный поиск')
    except (OSError, ValueError, KeyError, TypeError):
        return failure('lsp_error', 'LSP недоступен, неверный ответ или версия файла изменилась')
    finally:
        if client is not None:
            client.close()

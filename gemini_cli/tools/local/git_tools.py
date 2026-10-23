"""Ограниченные argv-команды Git в точно выбранном корне workspace."""
import os
from pathlib import Path
from contextlib import nullcontext

from ...client.process import ManagedProcess
from .workspace import resolve_safe_path, is_sensitive_read_path, path_has_links
from ..results import failure, success


def selected_paths(root: str, files: list) -> list[str]:
    if not isinstance(files, list) or not 1 <= len(files) <= 64:
        raise ValueError('Нужен явный выбор 1–64 файлов')
    paths = []
    for path in files:
        if (not isinstance(path, str) or not path or len(path) > 500 or '\x00' in path
                or os.path.isabs(path) or '\\' in path
                or any(part in {'.git', '..'} for part in Path(path).parts)):
            raise ValueError('Нужны относительные пути файлов')
        full = resolve_safe_path(root, path)
        if (full is None or is_sensitive_read_path(full) or path_has_links(os.path.join(root, path))
                or os.path.isdir(full)):
            raise ValueError('Недопустимый путь Git')
        paths.append(os.path.relpath(full, root).replace(os.sep, '/'))
    if len(set(paths)) != len(paths):
        raise ValueError('Повторные пути')
    return paths


class Git:
    def __init__(self, root: str, *, cancelled=lambda: False, monitor=nullcontext):
        self.root = os.path.realpath(root)
        self.cancelled, self.monitor = cancelled, monitor
        result = self.run(['rev-parse', '--show-toplevel'])
        if result['truncated'] or str(Path(result['stdout'].strip()).resolve()) != self.root:
            raise ValueError('Workspace должен совпадать с корнем Git-репозитория')

    def run(self, args: list[str], *, env=None, timeout=120) -> dict:
        inherited = {key: value for key, value in os.environ.items() if key not in {
            'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR', 'GIT_NAMESPACE',
            'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES'}}
        variables = {**inherited, 'GIT_LITERAL_PATHSPECS': '1', 'GIT_TERMINAL_PROMPT': '0',
                     'GIT_OPTIONAL_LOCKS': '0', 'GIT_PAGER': 'cat', **(env or {})}
        process = ManagedProcess(['git', '-c', 'core.quotepath=false', '-c', 'core.fsmonitor=false', *args],
                                 self.root, env=variables, limit=32768)
        try:
            with self.monitor():
                status = process.wait(timeout=timeout, cancelled=self.cancelled)
            data = {'stdout': process.stdout.read(), 'stderr': process.stderr.read(),
                    'exit_code': process.poll(), 'process_status': status,
                    'truncated': process.stdout.truncated or process.stderr.truncated}
            if status != 'completed' or data['exit_code'] != 0:
                raise GitError(data)
            return data
        finally:
            process.close()


class GitError(OSError):
    def __init__(self, data):
        super().__init__('Ошибка Git')
        self.data = data


def git_read(args: dict, root: str, *, approve, cancelled=lambda: False, monitor=nullcontext) -> dict:
    try:
        paths = selected_paths(root, args.get('files'))
        action = args.get('action')
        if action not in {'status', 'diff', 'log', 'blame'}:
            raise ValueError('Ожидается status/diff/log/blame')
        if not approve('Git ' + action + ': ' + ', '.join(paths) + '; результат будет отправлен модели'):
            return failure('denied', 'Чтение Git отклонено')
        git = Git(root, cancelled=cancelled, monitor=monitor)
        if action == 'status':
            command = ['status', '--porcelain=v1', '-z', '--untracked-files=all', '--', *paths]
        elif action == 'diff':
            command = ['diff', '--no-ext-diff', '--no-textconv', '--no-color',
                       *(['--cached'] if args.get('staged', False) else []), '--', *paths]
        elif action == 'log':
            command = ['log', '-n', '20', '--format=%H%x00%s%x00', '--', *paths]
        else:
            start, end = args.get('start_line', 1), args.get('end_line', 100)
            if (len(paths) != 1 or type(start) is not int or type(end) is not int
                    or not 1 <= start <= end or end - start >= 100):
                raise ValueError('Blame: один файл и диапазон до 100 строк')
            command = ['blame', '--line-porcelain', '-L', f'{start},{end}', '--', *paths]
        result = git.run(command)
        data = {'action': action, 'files': paths, **result}
        if action == 'status':
            fields, rows, index = result['stdout'].split('\x00'), [], 0
            while index < len(fields) and fields[index]:
                field = fields[index]; index += 1
                row = {'index': field[0], 'worktree': field[1], 'path': field[3:]}
                if field[0] in 'RC' or field[1] in 'RC':
                    if index < len(fields):
                        row['original_path'] = fields[index]; index += 1
                rows.append(row)
            data['entries'] = rows
        return success(data, truncated=result['truncated'])
    except GitError as error:
        return {'status': 'error', 'error': {'code': 'git_error', 'message': 'Git завершился с ошибкой'},
                'data': error.data}
    except (OSError, ValueError):
        return failure('unavailable', 'Git недоступен, неверный корень или выбранные пути')

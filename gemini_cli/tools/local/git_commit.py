"""Одноразовый план коммита выбранных файлов, без staging посторонних правок."""
from collections import OrderedDict
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import tempfile
from contextlib import nullcontext

from .git_tools import Git, GitError, selected_paths
from .changes import snapshot
from ..results import failure, success

_PLANS = OrderedDict()


def index_hash(git: Git) -> str:
    result = git.run(['rev-parse', '--path-format=absolute', '--git-path', 'index'])
    path = Path(result['stdout'].strip())
    if not path.exists():
        return 'missing'
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('Index слишком большой')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(git: Git, paths: list[str]):
    head = git.run(['rev-parse', 'HEAD'])['stdout'].strip()
    return head, index_hash(git), [snapshot(git.root, path) for path in paths]


def prepare(args: dict, root: str, *, approve, cancelled=lambda: False, monitor=nullcontext):
    paths = selected_paths(root, args.get('files'))
    message, task = args.get('message'), args.get('task', '')
    if (not isinstance(message, str) or not message.strip() or len(message) > 2000 or '\x00' in message
            or not isinstance(task, str) or len(task) > 2000):
        raise ValueError('Нужно сообщение коммита и ограниченный контекст задачи')
    if not approve('Подготовить выбранный diff для коммита: ' + ', '.join(paths)):
        return failure('denied', 'Чтение diff отклонено')
    git = Git(root, cancelled=cancelled, monitor=monitor)
    version = identity(git, paths)
    diff = git.run(['diff', 'HEAD', '--no-ext-diff', '--no-textconv', '--no-color', '--', *paths])
    if diff['truncated']:
        raise ValueError('Diff слишком большой; выберите меньше файлов')
    untracked = git.run(['ls-files', '--others', '--exclude-standard', '-z', '--', *paths])
    if untracked['truncated']:
        raise ValueError('Слишком много файлов')
    untracked_paths = untracked['stdout'].split('\x00')
    preview = diff['stdout']
    for path, snap in zip(paths, version[2]):
        if path in untracked_paths and snap.data is not None:
            preview += '\nНовый файл: ' + path + '\n' + snap.data.decode('utf-8')
    if not preview.strip() or len(preview.encode('utf-8')) > 32768:
        raise ValueError('Пустой или слишком большой выбранный diff')
    if identity(git, paths) != version:
        raise ValueError('Diff изменился при подготовке')
    token = secrets.token_urlsafe(24)
    _PLANS[token] = (git.root, paths, message, task, version, preview)
    while len(_PLANS) > 4:
        _PLANS.popitem(last=False)
    return success({'token': token, 'files': paths, 'message': message, 'task': task,
                    'diff': preview, 'selection': 'Полное текущее содержимое выбранных файлов; остальные не включаются'})


def git_commit(args: dict, root: str, *, approve, cancelled=lambda: False, monitor=nullcontext) -> dict:
    try:
        if args.get('action') == 'prepare':
            return prepare(args, root, approve=approve, cancelled=cancelled, monitor=monitor)
        if args.get('action') != 'commit':
            raise ValueError('Ожидается prepare или commit')
        plan = _PLANS.pop(args.get('token', ''), None)
        if plan is None or Path(root).resolve() != Path(plan[0]):
            raise ValueError('Нет одноразового плана для workspace')
        _, paths, message, task, expected, preview = plan
        git = Git(root, cancelled=cancelled, monitor=monitor)
        if identity(git, paths) != expected:
            raise ValueError('HEAD, index или файлы изменились после просмотра')
        if not approve('Создать commit выбранных файлов?\n' + message + '\nЗадача: ' + task + '\n\n' + preview):
            return failure('denied', 'Коммит отклонён')
        if cancelled():
            return failure('cancelled', 'Коммит отменён до запуска')
        if identity(git, paths) != expected:
            raise ValueError('Diff изменился во время подтверждения')
        # Hold the real index lock while Git uses its own selected-file index.
        # Hooks still run normally; this also supports previously untracked files.
        index = Path(git.run(['rev-parse', '--path-format=absolute', '--git-path', 'index'])['stdout'].strip())
        lock = index.with_name(index.name + '.lock')
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            if identity(git, paths) != expected:
                raise ValueError('Index изменился до блокировки')
            with tempfile.TemporaryDirectory(prefix='gemini-commit-') as directory:
                alternate = Path(directory, 'index')
                env = {'GIT_INDEX_FILE': str(alternate)}
                git.run(['read-tree', 'HEAD'], env=env)
                git.run(['add', '--', *paths], env=env)
                if identity(git, paths) != expected:
                    raise ValueError('Файлы изменились при подготовке index')
                result = git.run(['commit', '-m', message], env=env, timeout=1500)
                head = git.run(['rev-parse', 'HEAD'])['stdout'].strip()
                # Refresh only selected entries; retain every unrelated staged entry.
                if index.exists():
                    shutil.copy2(index, alternate)
                else:
                    alternate.unlink(missing_ok=True)
                git.run(['reset', '--quiet', 'HEAD', '--', *paths], env=env)
                with os.fdopen(descriptor, 'wb') as stream:
                    descriptor = None
                    stream.write(alternate.read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(lock, index)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            lock.unlink(missing_ok=True)
        return success({'commit': head, 'files': paths, 'output': result['stdout'],
                        'stderr': result['stderr']})
    except GitError as error:
        return {'status': 'error', 'error': {'code': 'git_error', 'message': 'Коммит не завершён; проверьте hook/output'},
                'data': error.data}
    except (OSError, ValueError, TypeError):
        return failure('conflict', 'План недоступен, изменился diff или Git; подготовьте и просмотрите заново')

"""PR через явно включённый GitHub MCP; никакого push, merge или скрытых повторов."""
import json
import re
from contextlib import nullcontext

from ..tools.local.git_tools import Git, GitError
from ..tools.results import failure, success
from ..protocol.mcp import tool_name


def unpack(raw: str):
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get('isError') or value.get('status') == 'error' or value.get('truncated'):
        raise ValueError('Ошибка или усечение MCP')
    if 'structured' in value:
        return value['structured']
    parts = value.get('content')
    if not isinstance(parts, list) or len(parts) != 1 or parts[0].get('type') != 'text':
        raise ValueError('Неподдерживаемый результат GitHub MCP')
    return json.loads(parts[0]['text'])


def remote_repository(git):
    remote = git.run(['remote', 'get-url', 'origin'])['stdout'].strip()
    match = re.fullmatch(r'(?:git@github\.com:|https://github\.com/)([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?', remote)
    if not match:
        raise ValueError('Нужен origin на github.com без встроенных credentials')
    branch = git.run(['symbolic-ref', '--short', 'HEAD'])['stdout'].strip()
    if not branch or len(branch) > 200:
        raise ValueError('Нужна текущая ветка')
    return *match.groups(), branch


def github_pr(args: dict, root: str, *, manager, approve, cancelled=lambda: False,
              invoke=lambda operation: operation(), monitor=nullcontext) -> dict:
    try:
        action, server, base = args.get('action'), args.get('server', 'github'), args.get('base', 'dev')
        if action not in {'create', 'update', 'checks'} or not isinstance(base, str) or not 1 <= len(base) <= 200:
            raise ValueError('Ожидается create/update/checks и base')
        if manager is None or server not in manager.enabled:
            return failure('mcp_disabled', 'Включите персональное GitHub MCP подключение через /mcp')
        git = Git(root, cancelled=cancelled, monitor=monitor)
        owner, repo, branch = remote_repository(git)
        if branch == base:
            raise ValueError('PR требует отдельную feature-ветку')
        common = {'owner': owner, 'repo': repo}
        enabled = {row['name'] for row in manager.declarations()}
        required = {'list_pull_requests', 'pull_request_read' if action == 'checks' else
                    'create_pull_request' if action == 'create' else 'update_pull_request'}
        if any(tool_name(server, name) not in enabled for name in required):
            return failure('tool_unavailable', 'Выберите нужные PR-инструменты GitHub в приватном mcp.json')
        def call(name, values):
            if cancelled():
                raise InterruptedError()
            return unpack(manager.call(tool_name(server, name), values, approve=approve,
                                       cancelled=cancelled, invoke=invoke))
        found = call('list_pull_requests', {**common, 'state': 'open', 'head': owner + ':' + branch,
                                           'base': base, 'perPage': 100, 'page': 1})
        if not isinstance(found, list) or len(found) >= 100:
            raise ValueError('Неполный список PR; создание запрещено')
        existing = []
        for row in found:
            if (not isinstance(row, dict) or not isinstance(row.get('head'), dict)
                    or not isinstance(row.get('base'), dict)):
                raise ValueError('Нельзя проверить существующий PR')
            if row['head'].get('ref') == branch and row['base'].get('ref') == base:
                existing.append(row)
        if len(existing) > 1:
            raise ValueError('Неоднозначный существующий PR')
        number = existing[0].get('number') if existing else None
        if existing and (type(number) is not int or number < 1):
            raise ValueError('Неверный номер существующего PR')
        if action == 'create' and number is not None:
            return success({'number': number, 'url': f'https://github.com/{owner}/{repo}/pull/{number}',
                            'existing': True})
        if action != 'create' and (type(number) is not int or number < 1):
            return failure('not_found', 'Открытый PR текущей ветки в выбранную base не найден')
        if action == 'checks':
            status = call('pull_request_read', {**common, 'pullNumber': number, 'method': 'get_status'})
            checks = call('pull_request_read', {**common, 'pullNumber': number, 'method': 'get_check_runs', 'perPage': 100})
            return success({'url': f'https://github.com/{owner}/{repo}/pull/{number}',
                            'status': status, 'checks': checks, 'completeness': 'Проверьте пагинацию; неизвестное не PASS'})
        title, body = args.get('title'), args.get('body')
        if (not isinstance(title, str) or not title.strip() or len(title) > 200
                or not isinstance(body, str) or not body.strip() or len(body) > 4000):
            raise ValueError('Нужны title до 200 и body до 4000 символов')
        values = {**common, 'title': title, 'body': body}
        if action == 'create':
            values.update({'base': base, 'head': branch, 'draft': True})
            result = call('create_pull_request', values)
            if not isinstance(result, dict):
                raise ValueError('Неизвестный результат публикации; проверьте список PR')
            number = result.get('number')
            if number is None:
                link = result.get('html_url', result.get('url', ''))
                match = re.fullmatch(r'https://(?:github\.com/' + re.escape(owner + '/' + repo) +
                    r'/pull|api\.github\.com/repos/' + re.escape(owner + '/' + repo) + r'/pulls)/(\d+)', link)
                number = int(match[1]) if match else None
        else:
            call('update_pull_request', {**values, 'pullNumber': number})
        if type(number) is not int or number < 1:
            raise ValueError('Неизвестный номер; перед повтором проверьте PR текущей ветки')
        return success({'number': number, 'url': f'https://github.com/{owner}/{repo}/pull/{number}',
                        'existing': action == 'update'})
    except InterruptedError:
        return failure('cancelled', 'PR-операция отменена; проверьте удалённое состояние перед повтором')
    except (OSError, ValueError, TypeError, KeyError):
        return failure('pr_error', 'PR недоступен: проверьте origin, ветку, base, права/401 и каталог MCP; повтора не было')

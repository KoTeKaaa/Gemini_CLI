"""Явное управление MCP без обращений к LLM."""

import json
import shlex
from rich.text import Text
from .input import result_panel, safe_label

USAGE = ('/mcp help — пошаговый гайд: настройка, вход и первое подключение\n'
         '/mcp — подключения и состояние\n/mcp tools имя — каталог и причины отказа\n'
         '/mcp check имя — подключить и обновить каталог\n/mcp enable имя — включить набор\n'
         '/mcp disable имя — отключить и завершить процесс\n'
         '/mcp login имя memory|keyring — персональный вход\n/mcp logout имя — удалить локальные credentials\n'
         'Пример: /mcp check github → /mcp enable github\n'
         'Конфигурация: приватный каталог CLI/mcp.json; процессы не запускаются при чтении.')


def prompt_secret(label, *, input, output):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import DummyHistory
    # Share the chat's input, including keys already queued after command Enter.
    secret = PromptSession(input=input, output=output, history=DummyHistory())
    try:
        return secret.prompt(label, is_password=True)
    finally:
        secret.default_buffer.reset()


def command(text, manager=None, *, console, read_secret, manager_factory=None):
    try:
        parts = shlex.split(text)
        if parts == ['/mcp', 'help']:
            from .integration_help import show_guide
            show_guide('mcp')
            return
        if manager_factory is not None:
            manager = manager_factory()
        if parts == ['/mcp']:
            lines = [f'{name}: {"включён" if name in manager.enabled else "отключён"} · {c.transport}'
                     for name, c in manager.connections.items()]
            console.print(result_panel('\n'.join(lines or ['Подключений нет.']) + '\n\n' + USAGE, title='MCP'))
            return
        if len(parts) not in (3, 4) or parts[1] not in {'tools', 'check', 'enable', 'disable', 'login', 'logout'}:
            raise ValueError()
        action, name = parts[1:3]
        if name not in manager.connections or len(parts) == 4 and action != 'login':
            raise ValueError()
        if action == 'login':
            if len(parts) != 4 or parts[3] not in {'memory', 'keyring'}:
                raise ValueError()
            store = manager.storage(name, persistent=parts[3] == 'keyring')
            c = manager.connections[name]
            if c.auth == 'bearer':
                token = read_secret('Персональный bearer MCP: ')
                if not token:
                    raise ValueError()
                store.set('bearer', token)
            elif c.transport == 'stdio':
                for key in c.env_keys:
                    value = read_secret(f'MCP {key}: ')
                    if not value:
                        raise ValueError()
                    store.set(key, value)
            manager.connect(name, login=c.auth == 'oauth')
        elif action == 'logout':
            manager.disconnect(name)
            manager.storage(name).clear(extra=manager.connections[name].env_keys)
        elif action == 'disable':
            manager.disconnect(name)
        elif action == 'enable':
            manager.enable(name)
        elif action == 'check':
            manager.connect(name)
        elif action == 'tools':
            declarations, routes, rejected = manager.catalogs.get(name, ([], {}, {}))
            lines = [f'{safe_label(routes[row["name"]])} → {row["name"]}' for row in declarations]
            lines.extend(f'{safe_label(original)}: недоступен — {reason}' for original, reason in rejected.items())
            console.print(result_panel('\n'.join(lines or ['Каталог пуст. Выполните /mcp check имя.']), title='MCP tools'))
            return
        message = 'MCP: действие выполнено.'
        if action == 'logout':
            message += ' Доступ на стороне сервиса отзывается в настройках этого сервиса.'
        console.print(result_panel(message, title='MCP'))
    except (Exception, KeyboardInterrupt):
        # SDK/OAuth exceptions may contain bearer tokens, bodies or private URLs.
        console.print(result_panel('MCP: действие не выполнено. Проверьте конфигурацию, runtime, вход и доступность сервиса.\n\n' + USAGE,
                                   title='MCP', error=True))


def approve_call(console, server, name, args):
    console.print(Text(f'MCP {server}/{safe_label(name)}\nАргументы: {safe_label(json.dumps(args, ensure_ascii=False))}\n'
                       'Вызов может читать/изменять данные и обращаться к внешнему сервису. '
                       'Результат будет отправлен модели. Внешние действия не откатываются через /undo.'))
    try:
        return input('Разрешить этот MCP-вызов? (y/n): ').strip().lower() == 'y'
    except (EOFError, KeyboardInterrupt):
        return False

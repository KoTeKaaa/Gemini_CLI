"""Локальный каталог/маршрутизация MCP; подключение только явным действием."""

import json

from ...protocol.mcp import validate_arguments, validate_declarations
from ...tools.results import failure
from .auth import Credentials, oauth_provider
from .catalog import catalog
from .config import load_connections
from .transport import Session, MCPUnavailable


class Manager:
    def __init__(self, root, binding, *, session_factory=Session):
        self.root, self.binding, self.session_factory = root, binding, session_factory
        self.connections = load_connections(root)
        self.sessions, self.credentials, self.catalogs = {}, {}, {}
        self.enabled = set()

    def storage(self, name, *, persistent=False):
        if name not in self.connections:
            raise ValueError('MCP: подключение отсутствует в приватном mcp.json')
        if name not in self.credentials or persistent and not self.credentials[name].backend:
            self.credentials[name] = Credentials(self.binding, self.connections[name], persistent=persistent)
        return self.credentials[name]

    def connect(self, name, *, login=False):
        c = self.connections[name]
        store = self.storage(name)
        secrets = {key: store.get(key) for key in c.env_keys if store.get(key)}
        if c.auth == 'bearer':
            token = store.get('bearer')
            if not token:
                raise ValueError('MCP: выполните /mcp login')
            secrets['bearer'] = token
        self.disconnect(name)
        session = self.session_factory(c, secrets=secrets,
            oauth=oauth_provider(c, store) if c.auth == 'oauth' else None,
            login=login, storage=store) if c.auth == 'oauth' else self.session_factory(c, secrets=secrets)
        try:
            self.catalogs[name] = catalog(name, session.request('list')['tools'])
        except Exception:
            session.close()
            raise
        self.sessions[name] = session
        return self.catalogs[name]

    def enable(self, name):
        if name not in self.sessions or self.sessions[name].closed:
            self.connect(name)
        values = [row for server in self.enabled | {name} for row in self.catalogs[server][0]]
        validate_declarations(values)
        self.enabled.add(name)

    def disconnect(self, name):
        self.enabled.discard(name)
        session = self.sessions.pop(name, None)
        if session:
            session.close()
        self.catalogs.pop(name, None)

    def declarations(self):
        return [row for server in sorted(self.enabled)
                if server in self.sessions and not self.sessions[server].closed
                for row in self.catalogs[server][0]]

    def call(self, name, args, *, approve, cancelled=lambda: False):
        for server in sorted(self.enabled):
            declarations, routes, _ = self.catalogs[server]
            if name not in routes:
                continue
            try:
                declaration = next(row for row in declarations if row['name'] == name)
                if not isinstance(args, dict) or len(json.dumps(args).encode()) > 8192:
                    raise ValueError('MCP: слишком большие аргументы')
                validate_arguments(args, declaration['parameters'])
                if cancelled():
                    return json.dumps(failure('cancelled', 'MCP: ход отменён'))
                if not approve(server, routes[name], args):
                    return json.dumps(failure('declined', 'MCP: пользователь отказал в вызове'))
                if cancelled():
                    return json.dumps(failure('cancelled', 'MCP: ход отменён'))
                return self.sessions[server].request('call', routes[name], args, cancelled=cancelled)
            except (ValueError, MCPUnavailable):
                return json.dumps(failure('mcp_unavailable', 'MCP: вызов отклонён или сервис недоступен'))
        return json.dumps(failure('mcp_disabled', 'MCP: набор отключён или инструмент отсутствует'))

    def close(self):
        for name in list(self.sessions):
            self.disconnect(name)
        for store in self.credentials.values():
            store.memory.clear()

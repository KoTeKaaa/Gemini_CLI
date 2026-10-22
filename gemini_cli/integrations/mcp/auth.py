"""Персональные credentials MCP: OS keyring либо явно выбранная память."""

import asyncio
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlsplit
import webbrowser

from ...client.secrets import system_backend, KeyStorageUnavailable


class Credentials:
    def __init__(self, binding, connection, *, persistent=False, backend_factory=system_backend):
        identity = json.dumps([binding, connection.name, connection.url, connection.command, connection.args])
        self.service = 'gemini_cli.mcp.' + hashlib.sha256(identity.encode()).hexdigest()
        self.backend = backend_factory() if persistent else None
        self.memory = {}

    def get(self, key):
        try:
            return self.memory.get(key) or (self.backend.get_password(self.service, key) if self.backend else None)
        except Exception:
            raise KeyStorageUnavailable('MCP: хранилище ОС недоступно') from None

    def set(self, key, value):
        if not isinstance(value, str) or not value or len(value) > 32768:
            raise ValueError('MCP: недопустимый credential')
        try:
            if self.backend:
                self.backend.set_password(self.service, key, value)
            self.memory[key] = value
        except Exception:
            raise KeyStorageUnavailable('MCP: credential не сохранён') from None

    def clear(self):
        for key in ('bearer', 'tokens', 'client'):
            try:
                if self.backend and self.backend.get_password(self.service, key) is not None:
                    self.backend.delete_password(self.service, key)
            except Exception:
                raise KeyStorageUnavailable('MCP: credential не удалён') from None
        self.memory.clear()

    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken
        raw = self.get('tokens')
        return OAuthToken.model_validate_json(raw) if raw else None

    async def set_tokens(self, tokens):
        self.set('tokens', tokens.model_dump_json())

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull
        raw = self.get('client')
        return OAuthClientInformationFull.model_validate_json(raw) if raw else None

    async def set_client_info(self, client_info):
        self.set('client', client_info.model_dump_json())


def oauth_provider(connection, storage, redirect_uri='http://127.0.0.1:1/callback', *,
                   redirect_handler=None, callback_handler=None):
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientMetadata

    async def no_interactive(*args):
        raise ValueError('MCP: выполните /mcp login')

    return OAuthClientProvider(connection.url, OAuthClientMetadata(
        client_name='Gemini CLI', redirect_uris=[redirect_uri],
        grant_types=['authorization_code', 'refresh_token'], response_types=['code'],
        token_endpoint_auth_method='none'), storage,
        redirect_handler=redirect_handler or no_interactive,
        callback_handler=callback_handler or no_interactive)


class BrowserLogin:
    def __init__(self, connection, storage):
        self.connection, self.storage = connection, storage
        self.state = None
        self.callback = None

    async def __aenter__(self):
        self.callback = asyncio.get_running_loop().create_future()
        self.server = await asyncio.start_server(self._receive, '127.0.0.1', 0, limit=8192)
        port = self.server.sockets[0].getsockname()[1]
        return oauth_provider(self.connection, self.storage,
            f'http://127.0.0.1:{port}/callback', redirect_handler=self._redirect,
            callback_handler=self._callback)

    async def _redirect(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password:
            raise ValueError('MCP OAuth: требуется HTTPS авторизация')
        self.state = parse_qs(parsed.query).get('state', [None])[0]
        if not self.state or not await asyncio.to_thread(webbrowser.open, url):
            raise ValueError('MCP OAuth: браузер недоступен')

    async def _receive(self, reader, writer):
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            method, target, _ = line.decode('ascii').strip().split(' ')
            parsed, query = urlsplit(target), parse_qs(urlsplit(target).query)
            state = query.get('state', [''])[0]
            code = query.get('code', [''])[0]
            if (method != 'GET' or parsed.path != '/callback' or not self.state or
                    not secrets.compare_digest(state, self.state) or not code or self.callback.done()):
                raise ValueError('Некорректный OAuth callback')
            from mcp.shared.auth import AuthorizationCodeResult
            self.callback.set_result(AuthorizationCodeResult(code=code, state=state,
                                                            iss=query.get('iss', [None])[0]))
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK')
        except Exception:
            writer.write(b'HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
        finally:
            await writer.drain()
            writer.close()
            await writer.wait_closed()

    async def _callback(self):
        return await asyncio.wait_for(self.callback, self.connection.timeout)

    async def __aexit__(self, *args):
        self.server.close()
        await self.server.wait_closed()
        if not self.callback.done():
            self.callback.cancel()

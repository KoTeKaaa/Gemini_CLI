import asyncio
import unittest
from unittest.mock import Mock

from gemini_cli.integrations.mcp.auth import Credentials, BrowserLogin
from gemini_cli.integrations.mcp.config import Connection


class MCPAuthTest(unittest.TestCase):
    def test_isolation_and_clear(self):
        connection = Connection('x', 'http', url='https://example.com/mcp')
        first, other = Credentials(('remote', 'account1'), connection), Credentials(('remote', 'account2'), connection)
        self.assertNotEqual(first.service, other.service)
        first.set('bearer', 'private')
        self.assertIsNone(other.get('bearer'))
        first.clear()
        self.assertIsNone(first.get('bearer'))

    def test_no_plaintext_fallback(self):
        from gemini_cli.client.secrets import KeyStorageUnavailable
        connection = Connection('x', 'http', url='https://example.com')
        with self.assertRaises(KeyStorageUnavailable):
            Credentials('profile', connection, persistent=True,
                        backend_factory=Mock(side_effect=KeyStorageUnavailable()))

    def test_callback_requires_state_and_ignores_replay(self):
        async def run():
            connection = Connection('x', 'http', url='https://example.com', timeout=1)
            login = BrowserLogin(connection, Credentials('profile', connection))
            async with login:
                login.state = 'expected'
                port = login.server.sockets[0].getsockname()[1]
                async def request(state):
                    reader, writer = await asyncio.open_connection('127.0.0.1', port)
                    writer.write(f'GET /callback?state={state}&code=private HTTP/1.1\r\n\r\n'.encode())
                    await writer.drain()
                    result = await reader.read()
                    writer.close()
                    await writer.wait_closed()
                    return result
                self.assertIn(b'400', await request('wrong'))
                self.assertFalse(login.callback.done())
                self.assertIn(b'200', await request('expected'))
                self.assertIn(b'400', await request('expected'))
                self.assertEqual((await login._callback()).code, 'private')
        asyncio.run(run())

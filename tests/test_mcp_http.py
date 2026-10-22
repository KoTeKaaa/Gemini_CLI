import asyncio
import unittest
from unittest.mock import patch

from gemini_cli.integrations.mcp.config import Connection
from gemini_cli.integrations.mcp.http import http_client


class MCPHTTPTest(unittest.TestCase):
    def test_guards_and_bounded_body(self):
        import httpx2
        async def run():
            connection = Connection('x', 'http', url='http://127.0.0.1:8000/mcp', allow_private=True)
            with patch.object(httpx2.AsyncHTTPTransport, 'handle_async_request') as send:
                send.return_value = httpx2.Response(302, headers={'Location': 'https://other.invalid'})
                async with http_client(connection, bearer='private') as client:
                    with self.assertRaises(ValueError):
                        await client.get(connection.url)
                    with self.assertRaises(ValueError):
                        await client.get('https://other.invalid')
                self.assertEqual(send.call_count, 1)
            for response in (httpx2.Response(200, stream=httpx2.ByteStream(b'x' * 262145)),
                             httpx2.Response(200, headers={'content-encoding': 'gzip'})):
                with patch.object(httpx2.AsyncHTTPTransport, 'handle_async_request', return_value=response):
                    async with http_client(connection) as client:
                        with self.assertRaises(ValueError):
                            await client.get(connection.url)
            for code in (401, 429):
                with patch.object(httpx2.AsyncHTTPTransport, 'handle_async_request',
                                  return_value=httpx2.Response(code)):
                    async with http_client(connection) as client:
                        self.assertEqual((await client.get(connection.url)).status_code, code)
        asyncio.run(run())

    def test_public_dns_is_pinned_before_request(self):
        import httpx2
        from gemini_cli.tools.web.fetch import Target
        async def run():
            connection = Connection('x', 'http', url='https://example.com/mcp')
            target = Target(connection.url, 'https', 'example.com', 443, '/mcp',
                            ((2, 1, 6, '', ('93.184.216.34', 443)),))
            with patch('gemini_cli.integrations.mcp.http.validate_target', return_value=target), \
                    patch.object(httpx2.AsyncHTTPTransport, 'handle_async_request',
                                 return_value=httpx2.Response(200, content=b'{}')) as send:
                async with http_client(connection) as client:
                    await client.get(connection.url)
                request = send.call_args.args[0]
                self.assertEqual(request.url.host, '93.184.216.34')
                self.assertEqual(request.extensions['sni_hostname'], 'example.com')
                self.assertEqual(request.headers['host'], 'example.com')
        asyncio.run(run())

    def test_real_http_discovery_and_call(self):
        import socket
        import subprocess
        import sys
        import time
        from pathlib import Path
        from gemini_cli.integrations.mcp.transport import Session
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen([sys.executable,
            str(Path(__file__).with_name('mcp_fixture.py')), str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.1):
                        break
                except OSError:
                    time.sleep(.05)
            session = Session(Connection('http', 'http', url=f'http://127.0.0.1:{port}/mcp',
                                         allow_private=True, timeout=5))
            try:
                self.assertTrue(session.request('list')['tools'])
                self.assertIn('real-http', session.request('call', 'echo', {'text': 'real-http'}))
            finally:
                session.close()
        finally:
            process.terminate()
            process.wait(timeout=5)

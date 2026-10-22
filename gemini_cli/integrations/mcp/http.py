"""Streamable HTTP: TLS, pinned public IP, bounded responses, no redirects."""

import asyncio
import time
from urllib.parse import urlsplit

from ...tools.web.fetch import validate_target, timed_resolver
from .config import validate_url


def origin(url):
    parsed = urlsplit(str(url))
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)


def http_client(connection, *, bearer=None, oauth=None):
    import httpx2

    class BoundedStream(httpx2.AsyncByteStream):
        def __init__(self, stream):
            self.stream = stream

        async def __aiter__(self):
            size = 0
            async for chunk in self.stream:
                size += len(chunk)
                if size > 262144:
                    raise ValueError('MCP: ответ превышает лимит')
                yield chunk

        async def aclose(self):
            await self.stream.aclose()

    class GuardedTransport(httpx2.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx2.AsyncHTTPTransport(verify=True, trust_env=False, retries=0)

        async def handle_async_request(self, request):
            url = str(request.url)
            if origin(url) != origin(connection.url) and request.headers.get('Authorization', '').startswith('Bearer '):
                raise ValueError('MCP: запрещена передача bearer другому origin')
            validate_url(url, connection.allow_private)
            # Pin the actual socket target; keep the original Host and TLS SNI.
            if not connection.allow_private:
                target = await asyncio.to_thread(validate_target, url,
                    resolver=timed_resolver(time.monotonic() + connection.timeout))
                request.headers['Host'] = request.url.netloc.decode('ascii')
                pinned = request.url.copy_with(host=target.addresses[0][4][0])
                request = httpx2.Request(request.method, pinned, headers=request.headers,
                    stream=request.stream, extensions={**request.extensions, 'sni_hostname': target.host})
            response = await self.inner.handle_async_request(request)
            if 300 <= response.status_code < 400:
                await response.aclose()
                raise ValueError('MCP: redirect отклонён; настройте конечный URL явно')
            response.stream = BoundedStream(response.stream)
            return response

        async def aclose(self):
            await self.inner.aclose()

    return httpx2.AsyncClient(transport=GuardedTransport(), auth=oauth,
        headers={'Authorization': 'Bearer ' + bearer} if bearer else {},
        follow_redirects=False, trust_env=False, timeout=connection.timeout)

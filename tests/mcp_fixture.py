"""Контрактный SDK-сервер; не обращается к внешним сервисам."""
import asyncio
from mcp.server import MCPServer

server = MCPServer('fixture')


@server.tool()
def echo(text: str) -> str:
    return text


@server.tool()
async def wait(seconds: int) -> str:
    await asyncio.sleep(seconds)
    return 'done'


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        server.run(transport='streamable-http', port=int(sys.argv[1]))
    else:
        server.run()

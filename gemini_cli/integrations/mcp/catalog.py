"""Каталог с устойчивыми именами; неподдерживаемые tools не объявляются."""

from ...protocol.mcp import tool_name, validate_declarations


def catalog(server, tools):
    accepted, rejected, routes = [], {}, {}
    for tool in tools:
        name = tool.get('name')
        if not isinstance(name, str) or not 1 <= len(name) <= 256:
            rejected['invalid'] = 'Неверное исходное имя'
            continue
        qualified = tool_name(server, name)
        declaration = {'name': qualified, 'description': str(tool.get('description') or '')[:512],
                       'parameters': tool.get('inputSchema')}
        try:
            validate_declarations([*accepted, declaration])
        except ValueError as error:
            rejected[name] = str(error)
            continue
        accepted.append(declaration)
        routes[qualified] = name
    return accepted, routes, rejected

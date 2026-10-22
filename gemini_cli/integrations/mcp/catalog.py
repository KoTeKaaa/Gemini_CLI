"""Каталог с устойчивыми именами; неподдерживаемые tools не объявляются."""

from ...protocol.mcp import tool_name, validate_declarations


def canonical_schema(schema):
    if not isinstance(schema, dict):
        return schema
    result = dict(schema)
    dialect = result.pop('$schema', None)
    if dialect not in (None, 'https://json-schema.org/draft/2020-12/schema', 'http://json-schema.org/draft-07/schema#'):
        raise ValueError('MCP: неизвестный dialect schema')
    for annotation in ('title', 'default', 'x-mcp-header'):
        result.pop(annotation, None)
    if isinstance(result.get('properties'), dict):
        result['properties'] = {name: canonical_schema(value) for name, value in result['properties'].items()}
    if 'items' in result:
        result['items'] = canonical_schema(result['items'])
    return result


def catalog(server, tools, selected=()):
    accepted, rejected, routes = [], {}, {}
    for tool in tools:
        name = tool.get('name')
        if not isinstance(name, str) or not 1 <= len(name) <= 256:
            rejected['invalid'] = 'Неверное исходное имя'
            continue
        if selected and name not in selected:
            continue
        qualified = tool_name(server, name)
        declaration = {'name': qualified, 'description': str(tool.get('description') or '')[:512],
                       'parameters': tool.get('inputSchema')}
        try:
            declaration['parameters'] = canonical_schema(declaration['parameters'])
            validate_declarations([*accepted, declaration])
        except ValueError as error:
            rejected[name] = str(error)
            continue
        accepted.append(declaration)
        routes[qualified] = name
    return accepted, routes, rejected

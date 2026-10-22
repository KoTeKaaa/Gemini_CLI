"""Ограниченные объявления MCP: чистый контракт без SDK и исполнения."""

import hashlib
import json
import re

MCP_PROTOCOL = 'mcp-tools-v1'
MCP_FEATURE = 'mcp'
MAX_MCP_TOOLS = 16
MCP_NAME = re.compile(r'mcp_[a-z][a-z0-9_]{0,23}_[0-9a-f]{16}\Z')
SCHEMA_KEYS = {'type', 'description', 'properties', 'required', 'items', 'enum', 'additionalProperties'}


def tool_name(server: str, original: str) -> str:
    return f'mcp_{server}_' + hashlib.sha256(original.encode()).hexdigest()[:16]


def validate_schema(schema, *, depth=0, root=True):
    if not isinstance(schema, dict) or set(schema) - SCHEMA_KEYS or depth > 5:
        raise ValueError('MCP: неподдерживаемая JSON Schema (refs/union/composition запрещены)')
    kind = schema.get('type')
    if not isinstance(kind, str) or kind not in {'object', 'array', 'string', 'integer', 'number', 'boolean'} or root and kind != 'object':
        raise ValueError('MCP: неподдерживаемый тип JSON Schema')
    if 'description' in schema and (not isinstance(schema['description'], str) or len(schema['description']) > 512):
        raise ValueError('MCP: слишком большое описание schema')
    if 'enum' in schema:
        enum = schema['enum']
        if (kind not in {'string', 'integer', 'number', 'boolean'} or not isinstance(enum, list) or
                not 1 <= len(enum) <= 32 or any(isinstance(v, (dict, list)) or v is None for v in enum)):
            raise ValueError('MCP: недопустимый enum')
    if kind == 'object':
        properties, required = schema.get('properties', {}), schema.get('required', [])
        if not isinstance(properties, dict) or len(properties) > 24:
            raise ValueError('MCP: слишком много свойств')
        if (not isinstance(required, list) or any(not isinstance(v, str) for v in required) or
                len(set(required)) != len(required) or not set(required) <= set(properties)):
            raise ValueError('MCP: неизвестные required свойства')
        if 'additionalProperties' in schema and schema['additionalProperties'] is not False:
            raise ValueError('MCP: свободные additionalProperties не поддерживаются')
        for name, value in properties.items():
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', name):
                raise ValueError('MCP: недопустимое имя свойства')
            validate_schema(value, depth=depth + 1, root=False)
    elif any(key in schema for key in ('properties', 'required', 'additionalProperties')):
        raise ValueError('MCP: объектные свойства у другого типа')
    if kind == 'array':
        validate_schema(schema.get('items'), depth=depth + 1, root=False)
    elif 'items' in schema:
        raise ValueError('MCP: items только у array')


def validate_declarations(values):
    if not isinstance(values, list) or len(values) > MAX_MCP_TOOLS:
        raise ValueError('MCP: не более 16 инструментов')
    try:
        size = len(json.dumps(values, allow_nan=False).encode())
    except (TypeError, ValueError, RecursionError):
        raise ValueError('MCP: некорректный JSON объявления') from None
    if size > 32768:
        raise ValueError('MCP: превышен размер объявлений')
    names = set()
    for value in values:
        if not isinstance(value, dict) or set(value) != {'name', 'description', 'parameters'}:
            raise ValueError('MCP: неверный формат объявления')
        name = value['name']
        if not isinstance(name, str) or not MCP_NAME.fullmatch(name) or name in names:
            raise ValueError('MCP: неверное или повторное имя')
        names.add(name)
        if not isinstance(value['description'], str) or len(value['description']) > 512:
            raise ValueError('MCP: неверное описание')
        validate_schema(value['parameters'])
    return names


def validate_arguments(value, schema):
    kind = schema['type']
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'string': isinstance(value, str), 'integer': type(value) is int,
             'number': type(value) in (int, float), 'boolean': type(value) is bool}[kind]
    if not valid or 'enum' in schema and value not in schema['enum']:
        raise ValueError('MCP: аргументы не соответствуют schema')
    if kind == 'object':
        properties = schema.get('properties', {})
        if not set(value) <= set(properties) or not set(schema.get('required', [])) <= set(value):
            raise ValueError('MCP: неизвестные или отсутствующие аргументы')
        for key, item in value.items():
            validate_arguments(item, properties[key])
    if kind == 'array':
        if len(value) > 64:
            raise ValueError('MCP: слишком длинный массив аргументов')
        for item in value:
            validate_arguments(item, schema['items'])


def validate_tool_payload(payload):
    from ..tools.definitions import TOOLS
    declarations = payload.get('mcp_tools', [])
    dynamic = validate_declarations(declarations)
    names = payload.get('supported_tools')
    if names is not None:
        if (not isinstance(names, list) or len(names) > 32 or any(not isinstance(v, str) for v in names) or
                len(set(names)) != len(names) or set(names) - set(TOOLS) != dynamic):
            raise ValueError('MCP: объявления должны соответствовать выбранным инструментам')
    elif dynamic:
        raise ValueError('MCP: требуется явный supported_tools')
    return declarations

import unittest
from gemini_cli.integrations.mcp.catalog import catalog
from gemini_cli.protocol.mcp import tool_name, validate_declarations, validate_arguments


class MCPSchemaTest(unittest.TestCase):
    def test_stable_distinct_names_and_rejection(self):
        tools = [{'name': 'read_local_files', 'inputSchema': {'type': 'object'}},
                 {'name': 'bad', 'inputSchema': {'type': 'object', '$ref': '#secret'}}]
        accepted, routes, rejected = catalog('demo', tools)
        self.assertEqual(accepted[0]['name'], tool_name('demo', 'read_local_files'))
        self.assertNotEqual(accepted[0]['name'], tool_name('other', 'read_local_files'))
        self.assertEqual(list(routes.values()), ['read_local_files'])
        self.assertIn('bad', rejected)

    def test_oversize_duplicate_and_unsafe_schemas(self):
        declaration = {'name': tool_name('x', 'a'), 'description': '', 'parameters': {'type': 'object'}}
        for values in ([declaration] * 2, [{**declaration, 'description': 'x' * 513}],
                       [{**declaration, 'parameters': {'type': 'object', 'additionalProperties': True}}],
                       [{**declaration, 'parameters': {'type': 'object', 'properties': {'x': {'type': ['string', 'null']}}}}]):
            with self.subTest(values=values), self.assertRaises((ValueError, TypeError)):
                validate_declarations(values)

    def test_sdk_annotations_and_explicit_tool_subset(self):
        tools = [{'name': 'echo', 'inputSchema': {'$schema': 'https://json-schema.org/draft/2020-12/schema',
                  'title': 'Echo', 'type': 'object', 'properties': {'text': {'type': 'string', 'title': 'Text', 'x-mcp-header': 'text'}}}},
                 {'name': 'unused', 'inputSchema': {'type': 'object'}}]
        accepted, routes, rejected = catalog('demo', tools, ('echo',))
        self.assertEqual(len(accepted), 1)
        self.assertNotIn('title', str(accepted))
        self.assertEqual(rejected, {})

    def test_disappeared_tool_has_reason(self):
        accepted, routes, rejected = catalog('demo', [], ('removed',))
        self.assertEqual(accepted, [])
        self.assertIn('removed', rejected)

    def test_arguments_validate_before_call(self):
        schema = {'type': 'object', 'properties': {'x': {'type': 'integer'}}, 'required': ['x']}
        validate_arguments({'x': 3}, schema)
        for args in ({'x': True}, {'unexpected': 3}, {}):
            with self.assertRaises(ValueError):
                validate_arguments(args, schema)

from types import SimpleNamespace
import unittest
from gemini_cli.backends.genai import stream_events, provider_tools
from gemini_cli.protocol.mcp import tool_name, validate_tool_payload


class MCPBackendTest(unittest.TestCase):
    def declaration(self):
        return {'name': tool_name('x', 'echo'), 'description': 'Echo', 'parameters': {'type': 'object'}}

    def test_declarations_and_unknown_calls(self):
        declaration = self.declaration()
        tools = provider_tools([], set(), [declaration])
        self.assertEqual(tools[0].function_declarations[0].name, declaration['name'])
        client = SimpleNamespace(models=SimpleNamespace(generate_content_stream=lambda **_: [
            SimpleNamespace(function_calls=[SimpleNamespace(name=declaration['name'], args={}, id='c')])]))
        events = list(stream_events(client, model='test', contents=[], supported_tools=[declaration['name']],
                                    mcp_tools=[declaration]))
        self.assertEqual(events[0]['call_id'], 'c')
        self.assertEqual(list(stream_events(client, model='test', contents=[], supported_tools=[]))[0]['type'], 'error')

    def test_payload_exact_dynamic_set(self):
        row = self.declaration()
        validate_tool_payload({'supported_tools': [row['name']], 'mcp_tools': [row]})
        for payload in ({'supported_tools': [row['name']]}, {'mcp_tools': [row]},
                        {'supported_tools': [], 'mcp_tools': [row]}):
            with self.assertRaises(ValueError):
                validate_tool_payload(payload)

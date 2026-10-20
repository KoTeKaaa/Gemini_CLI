"""Context metadata tests use mocked transports; no real credentials or network."""
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gemini_cli.backends import model_info as metadata
from gemini_cli.runtime.context_info import estimate_context


class ModelInfoTests(unittest.TestCase):
    def setUp(self):
        metadata._CACHE.clear()
        self.provider = SimpleNamespace(models=Mock())
        self.provider.models.get.return_value = SimpleNamespace(
            input_token_limit=1000, output_token_limit=100)

    def test_real_metadata_cached_per_scope_and_model(self):
        with patch.object(metadata, 'monotonic', return_value=10):
            result = metadata.model_info(self.provider, 'model', 'profile-a')
            self.assertEqual(result['input_token_limit'], 1000)
            result['input_token_limit'] = 1
            self.assertEqual(metadata.model_info(self.provider, 'model', 'profile-a')['input_token_limit'], 1000)
            self.assertEqual(self.provider.models.get.call_count, 1)
            metadata.model_info(self.provider, 'model', 'profile-b')
            metadata.model_info(self.provider, 'other', 'profile-a')
            self.assertEqual(self.provider.models.get.call_count, 3)
        with patch.object(metadata, 'monotonic', return_value=311):
            metadata.model_info(self.provider, 'model', 'profile-a')
        self.assertEqual(self.provider.models.get.call_count, 4)

    def test_cache_bounded_and_refresh_explicit(self):
        for index in range(metadata._CACHE_LIMIT + 1):
            metadata.model_info(self.provider, 'model', str(index))
        self.assertEqual(len(metadata._CACHE), metadata._CACHE_LIMIT)
        metadata.model_info(self.provider, 'model', '1', refresh=True)
        self.assertEqual(self.provider.models.get.call_count, metadata._CACHE_LIMIT + 2)

    def test_uncached_default_and_private_error(self):
        self.provider.models.get.side_effect = RuntimeError('private credentials')
        for _ in range(2):
            result = metadata.model_info(self.provider, 'model')
            self.assertIsNone(result['input_token_limit'])
            self.assertEqual(result['source'], 'unavailable')
            self.assertNotIn('private', str(result))
        self.assertEqual(self.provider.models.get.call_count, 2)

    def test_full_request_count_stays_unavailable_without_invalid_sdk_call(self):
        contents, tools = [{'parts': [{'text': 'hello'}]}], [{'function_declarations': []}]
        for instruction, declarations in (('instruction', tools), ('instruction', []), ('', tools)):
            with self.subTest(instruction=instruction, tools=bool(declarations)):
                result = metadata.count_context(self.provider, 'model', contents, instruction, declarations)
                self.assertIsNone(result['prompt_token_count'])
                self.assertEqual(result['source'], 'unavailable')
        self.provider.models.count_tokens.assert_not_called()
        estimate = estimate_context(contents, instruction='instruction', tools=tools, measured_usage=result)
        self.assertTrue(estimate['estimated'])
        self.assertEqual(estimate['source'], 'estimate')

    def test_bare_contents_count_and_private_failure(self):
        contents = [{'parts': [{'text': 'hello'}]}]
        self.provider.models.count_tokens.return_value = SimpleNamespace(total_tokens=42)
        result = metadata.count_context(self.provider, 'model', contents)
        self.assertEqual(result['prompt_token_count'], 42)
        self.provider.models.count_tokens.assert_called_once_with(model='model', contents=contents)
        self.provider.models.count_tokens.side_effect = RuntimeError('private')
        self.assertIsNone(metadata.count_context(self.provider, 'model', contents)['prompt_token_count'])

    def test_real_developer_sdk_conversion_reaches_mocked_transport_for_bare_contents(self):
        from google import genai
        with genai.Client(api_key='fixture', vertexai=False) as client, patch.object(
                client._api_client, 'request', return_value=SimpleNamespace(body='{"totalTokens":7}', headers={})) as transport:
            result = metadata.count_context(client, 'gemini-fixture', 'hello')
            self.assertEqual(result, {'prompt_token_count': 7, 'source': 'provider_count'})
            transport.assert_called_once()
            request = transport.call_args.args
            self.assertEqual(request[0], 'post')
            self.assertTrue(request[1].endswith(':countTokens'))
            self.assertIn('contents', request[2])
            self.assertNotIn('systemInstruction', request[2])
            self.assertNotIn('tools', request[2])
            unavailable = metadata.count_context(client, 'gemini-fixture', 'hello', 'instruction', [{}])
            self.assertEqual(unavailable, {'prompt_token_count': None, 'source': 'unavailable'})
            self.assertEqual(transport.call_count, 1)

    def test_import_does_not_require_sdk(self):
        result = subprocess.run([sys.executable, '-S', '-B', '-c',
            'import gemini_cli.backends.model_info; import gemini_cli.runtime.context_info; '
            'import sys; assert "google.genai" not in sys.modules'], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class ContextInfoTests(unittest.TestCase):
    def test_estimate_includes_instructions_tools_and_tool_results(self):
        base = estimate_context([{'role': 'user', 'content': 'hello'}])
        full = estimate_context([{'role': 'user', 'content': 'hello'},
            {'role': 'tool', 'content': 'tool result' * 30}],
            instruction='system' * 30, tools=[{'description': 'schema' * 30}])
        self.assertGreater(full['input_tokens'], base['input_tokens'])
        self.assertTrue(full['estimated'])
        self.assertEqual(full['source'], 'estimate')
        self.assertIsNone(full['input_token_limit'])
        self.assertIsNone(full['remaining_tokens'])

    def test_media_unknown_until_exact_count_available(self):
        contents = [{'parts': [{'inline_data': {'data': b'private image'}}]}]
        info = {'input_token_limit': 100, 'output_token_limit': 20}
        unknown = estimate_context(contents, info)
        self.assertIsNone(unknown['input_tokens'])
        self.assertTrue(unknown['has_unmeasured_media'])
        counted = estimate_context(contents, info, measured_usage={
            'prompt_token_count': 40, 'source': 'provider_count'})
        self.assertEqual(counted['remaining_tokens'], 60)
        self.assertEqual(counted['source'], 'provider_count')
        self.assertFalse(counted['estimated'])

    def test_usage_zero_and_exceeded_limits(self):
        result = estimate_context([], {'input_token_limit': 10}, measured_usage={'prompt_token_count': 0})
        self.assertEqual(result['input_tokens'], 0)
        result = estimate_context([], {'input_token_limit': 10}, measured_usage={'prompt_token_count': 20})
        self.assertEqual(result['remaining_tokens'], 0)
        self.assertEqual(result['source'], 'provider_usage')

    def test_tool_signature_is_counted_as_metadata_not_unknown_media(self):
        from google.genai import types
        contents = [types.Content(role='model', parts=[types.Part(
            function_call=types.FunctionCall(name='read_file_lines', args={'path': 'test.txt'}),
            thought_signature=b'sig')])]
        result = estimate_context(contents, {'input_token_limit': 10000})
        self.assertIsInstance(result['input_tokens'], int)
        self.assertEqual(result['source'], 'estimate')
        self.assertFalse(result['has_unmeasured_media'])

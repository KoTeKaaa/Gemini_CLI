import json
import unittest
from gemini_cli.integrations.documents.boundary import result
from gemini_cli.runtime.history import bounded_tool_result, persistent_history_rows


class DocumentPrivacyTests(unittest.TestCase):
    def test_unicode_structured_result_survives_shared_wire_bound(self):
        value = result('отчёт.pdf', [{'position': {'page': 1}, 'text': 'Приватный документ ' * 1000}])
        encoded = json.dumps(value, ensure_ascii=False)
        self.assertEqual(json.loads(bounded_tool_result(encoded))['source'], 'отчёт.pdf')
        self.assertTrue(value['truncated'])
        self.assertTrue(value['fragments'])

    def test_tool_content_redacted_from_persistence_and_context_copies(self):
        history = [{'role': 'user', 'content': 'read'},
                   {'role': 'model', 'name': 'read_document', 'args': {'filepath': 'a.pdf', 'selection': 'pages=1', 'secret': 'PRIVATE_RAW'}, 'content': 'call'},
                   {'role': 'tool', 'name': 'read_document', 'content': 'PRIVATE_EXTRACTED'}]
        persisted = persistent_history_rows(history)
        self.assertNotIn('PRIVATE', json.dumps(persisted))
        self.assertIn('PRIVATE_EXTRACTED', str(history))

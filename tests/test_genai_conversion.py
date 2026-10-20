import unittest
from gemini_cli.backends.genai import to_gemini


class GenaiConversionTest(unittest.TestCase):
    def test_batch_ids_signatures_and_result_order(self):
        history = [{"role": "user", "content": "task"}]
        for call_id in ("one", "two"):
            history.append({"role": "model", "name": "find_files", "args": {},
                            "call_id": call_id, "thought_signature": "cw=="})
        for call_id in ("one", "two"):
            history.append({"role": "tool", "name": "find_files", "call_id": call_id, "content": '{}'})
        result = to_gemini(history)
        self.assertEqual(len(result), 3)
        self.assertEqual([part.function_call.id for part in result[1].parts], ["one", "two"])
        self.assertEqual(result[1].parts[0].thought_signature, b"s")
        self.assertEqual([part.function_response.id for part in result[2].parts], ["one", "two"])

    def test_invalid_signature_rejected_without_http_dependency(self):
        with self.assertRaises(ValueError):
            to_gemini([{"role": "user", "content": "task"},
                       {"role": "model", "name": "find_files", "thought_signature": "invalid!"}])

import unittest
from gemini_cli.runtime.history import persistent_history_rows, trim_history, bounded_tool_result


class RuntimeHistoryTest(unittest.TestCase):
    def test_large_and_escaped_results_are_bounded_with_explicit_status(self):
        import json
        for content in ('a' * 40000, '\\"\n' * 15000, 'я😀' * 10000):
            bounded = bounded_tool_result(content)
            self.assertTrue(json.loads(bounded)["truncated"])
            self.assertLess(len(json.dumps(bounded, ensure_ascii=False).encode()), 16000)
            self.assertLess(len(bounded), 32768)
            self.assertLessEqual(len(json.dumps(bounded).encode()), 8192)
        self.assertEqual(bounded_tool_result('{"status":"ok"}'), '{"status":"ok"}')
    def test_trimming_preserves_current_batch_and_source(self):
        history = [{"role": "user", "content": "old"}] + [
            {"role": "tool", "content": str(index)} for index in range(8)
        ] + [{"role": "user", "content": "current"}, {"role": "tool", "content": "private"}]
        result = trim_history(history)
        self.assertIn("already_processed", result[1]["content"])
        self.assertEqual(history[1]["content"], "0")
        self.assertEqual(result[-1]["content"], "private")

    def test_restored_history_redacts_and_preserves_ids(self):
        rows = [{"role": "user", "content": "task"},
                {"role": "model", "name": "read_local_files", "content": "call", "call_id": "c",
                 "thought_signature": "cw=="},
                {"role": "tool", "name": "read_local_files", "content": "private"},
                {"role": "user", "content": "next"}]
        result = persistent_history_rows(rows, "next")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[1]["thought_signature"], "cw==")
        self.assertEqual(result[1]["call_id"], "c")
        self.assertNotIn("private", result[2]["content"])

    def test_interrupted_persistent_batch_is_completed_without_replay(self):
        import json
        rows = [{"role": "user", "content": "task"},
                {"role": "model", "name": "execute_command", "call_id": "a", "content": "call"},
                {"role": "model", "name": "execute_command", "call_id": "b", "content": "call"},
                {"role": "tool", "name": "execute_command", "call_id": "a", "content": "done"},
                {"role": "user", "content": "next"}]
        restored = persistent_history_rows(rows)
        self.assertEqual(restored[-2]["call_id"], "b")
        self.assertEqual(json.loads(restored[-2]["content"])["status"], "interrupted")
        self.assertEqual(restored[-1]["content"], "next")
        self.assertEqual(persistent_history_rows(restored), restored)

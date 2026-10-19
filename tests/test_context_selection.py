import unittest
from gemini_cli.runtime.context import select_context


class ContextSelectionTests(unittest.TestCase):
    def test_equal_prompts_are_distinguished_by_turn_identity(self):
        stored = [{"role": "user", "content": "same", "turn_id": "a"},
                  {"role": "model", "content": "first", "turn_id": "a"},
                  {"role": "user", "content": "same", "turn_id": "b"},
                  {"role": "model", "content": "second", "turn_id": "b"},
                  {"role": "user", "content": "same", "turn_id": "c"}]
        active = [{"role": "user", "content": "same"},
                  {"role": "model", "name": "execute_command", "call_id": "tool", "content": "call"},
                  {"role": "tool", "name": "execute_command", "call_id": "tool", "content": "done"}]
        result = select_context(stored, active, continuing=True, turn_id="c")
        self.assertEqual([r["content"] for r in result], ["same", "first", "same", "second", "same", "call", "done"])
        self.assertEqual(stored[-1]["turn_id"], "c")
        with self.assertRaises(ValueError):
            select_context(stored, active, continuing=True, turn_id="wrong")

    def test_long_temporary_history_is_preserved_and_private_tools_redacted(self):
        history = []
        for i in range(40):
            history.extend([{"role": "user", "content": str(i)}, {"role": "model", "content": "answer"}])
        history += [{"role": "user", "content": "old"},
                    {"role": "model", "name": "read_local_files", "content": "call"},
                    {"role": "tool", "name": "read_local_files", "content": "SECRET"},
                    {"role": "user", "content": "current"}]
        result = select_context(None, history)
        self.assertEqual(len(result), len(history))
        self.assertNotIn("SECRET", str(result))
        self.assertEqual(history[-2]["content"], "SECRET")

    def test_summary_replaces_only_identified_prefix(self):
        history = [{"role": "user", "content": "old", "id": "1"},
                   {"role": "model", "content": "old answer", "id": "2"},
                   {"role": "user", "content": "new", "id": "3"}]
        result = select_context(history, [], summary="task and decisions", summary_boundary="2")
        self.assertEqual(len(result), 2)
        self.assertIn("task and decisions", result[0]["content"])
        self.assertEqual(result[-1]["id"], "3")

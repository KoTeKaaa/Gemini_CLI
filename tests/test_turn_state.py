import logging
import unittest
from gemini_cli.runtime.turn import TurnState
from gemini_cli.client.tool_runner import execute_tool_calls


class TurnTests(unittest.TestCase):
    def test_late_duplicate_and_previous_turn(self):
        first, second = TurnState(), TurnState()
        old = first.request({})
        current = second.request({})
        self.assertFalse(second.accepts(old))
        self.assertTrue(second.accepts({**current, "sequence": 0}))
        self.assertFalse(second.accepts({**current, "sequence": 0}))
        newer = second.request({})
        self.assertFalse(second.accepts(current))
        self.assertTrue(second.accepts(newer))
        second.cancel()
        second.finish()
        self.assertEqual(second.status, "cancelled")
        self.assertFalse(second.accepts(newer))

    def test_cancellation_between_calls_keeps_ids_and_pairs(self):
        state, history, ran = TurnState(), [], []
        def handler(args, cwd):
            ran.append(args)
            state.cancel()
            return "done"
        calls = [{"name": "execute_command", "args": {"n": n}, "call_id": str(n),
                  "thought_signature": "signature"} for n in range(2)]
        execute_tool_calls(calls, history, ".", handlers={"execute_command": handler},
                           logger=logging.getLogger(__name__), state=state)
        self.assertEqual(ran, [{"n": 0}])
        self.assertEqual([r["call_id"] for r in history], ["0", "1", "0", "1"])
        self.assertEqual(history[1]["thought_signature"], "signature")
        self.assertIn("cancelled", history[-1]["content"])

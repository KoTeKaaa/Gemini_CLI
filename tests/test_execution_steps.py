import json
import logging
import unittest
from gemini_cli.runtime.turn import TurnState
from gemini_cli.client.tool_runner import execute_tool_calls


class StepTests(unittest.TestCase):
    def test_failed_cancelled_skipped_are_not_success(self):
        state = TurnState()
        state.request({})
        def fail(args, cwd):
            if args["n"] == 1:
                state.cancel()
                return json.dumps({"status": "cancelled"})
            raise ValueError("failure")
        calls = [{"name": "execute_command", "args": {"n": n}, "call_id": str(n)} for n in range(3)]
        execute_tool_calls(calls, [], ".", handlers={"execute_command": fail},
                           logger=logging.getLogger(__name__), state=state)
        self.assertEqual([s["status"] for s in state.steps()], ["failed", "cancelled", "skipped"])
        self.assertTrue(all("args" not in e and "content" not in e for e in state.events))

    def test_bounded_status_channel(self):
        state = TurnState()
        for index in range(200):
            state.record({"type": "step", "step_id": str(index), "status": "completed"})
        self.assertEqual(len(state.events), 64)
        self.assertEqual(len(state.steps()), 8)

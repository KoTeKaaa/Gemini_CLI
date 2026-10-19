import unittest
from unittest.mock import Mock
from gemini_cli.client.work_input import WorkInput
from gemini_cli.runtime.turn import TurnState


class WorkInputTests(unittest.TestCase):
    def test_escape_cancels_and_f2_is_forwarded(self):
        state, callback = TurnState(), Mock()
        keys = WorkInput(state, callback)
        keys.handle("f2")
        callback.assert_called_once_with("f2")
        self.assertFalse(state.cancelled.is_set())
        keys.handle("escape")
        self.assertTrue(state.cancelled.is_set())

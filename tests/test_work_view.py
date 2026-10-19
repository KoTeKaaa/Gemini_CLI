import io
import unittest
from rich.console import Console
from gemini_cli.client.work_view import WorkView
from gemini_cli.client.process import ProcessLog
from gemini_cli.runtime.turn import TurnState
from unittest.mock import Mock


class WorkViewTests(unittest.TestCase):
    def test_disclosure_scrolling_and_cancel(self):
        state = TurnState()
        view = WorkView(Console(file=io.StringIO(), width=60, height=10), state)
        process = Mock(stdout=ProcessLog(), stderr=ProcessLog())
        process.stdout.append("secret-output\n" + "line\n"*100 + "tail")
        view.set_process(process)
        view.update_text("answer")
        self.assertNotIn("tail", view.render().plain)
        view.handle("f2")
        self.assertIn("tail", view.render().plain)
        view.handle("pageup")
        self.assertNotIn("tail", view.render().plain)
        state.cancel()
        self.assertIn("отменено", view.render().plain)
        view.handle("f2")
        self.assertIn("answer", view.render().plain)

    def test_non_terminal_monitor_does_not_print_logs(self):
        output = io.StringIO()
        view = WorkView(Console(file=output), TurnState())
        with view.monitor():
            view.update_text("not duplicated")
        self.assertEqual(output.getvalue(), "")

import io
import unittest
from rich.console import Console
from gemini_cli.client.work_view import WorkView
from gemini_cli.client.process import ProcessLog
from gemini_cli.runtime.turn import TurnState
from unittest.mock import Mock, patch


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

    def test_monitor_keeps_spinner_inline_and_never_enters_alternate_screen(self):
        output = io.StringIO()
        console = Console(file=output, force_terminal=True, width=80)
        view = WorkView(console, TurnState())
        with patch.dict("os.environ", {"TERM": "xterm"}), \
                patch("gemini_cli.client.work_view.Live") as live:
            with view.monitor():
                renderable = live.call_args.kwargs["get_renderable"]()
                console.print(renderable)
            self.assertFalse(live.call_args.kwargs["screen"])
            self.assertTrue(live.call_args.kwargs["transient"])
        self.assertIn("Gemini думает", output.getvalue())
        self.assertNotIn("\x1b[?1049h", output.getvalue())

    def test_steps_are_hidden_until_f2(self):
        state = Mock(cancelled=Mock(is_set=lambda: False))
        state.steps.return_value = [{"name": "execute_command", "status": "running"}]
        view = WorkView(Console(file=io.StringIO()), state)
        self.assertNotIn("execute_command", view.render().plain)
        view.handle("f2")
        self.assertIn("execute_command", view.render().plain)
        view.handle("f2")
        self.assertNotIn("execute_command", view.render().plain)

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

    def test_monitor_keeps_spinner_and_uses_transient_alternate_screen(self):
        output = io.StringIO()
        console = Console(file=output, force_terminal=True, width=80)
        view = WorkView(console, TurnState())
        with patch.dict("os.environ", {"TERM": "xterm"}), \
                patch("gemini_cli.client.work_view.Live") as live:
            with view.monitor():
                renderable = live.call_args.kwargs["get_renderable"]()
                console.print(renderable)
            self.assertTrue(live.call_args.kwargs["screen"])
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

    def test_alternate_screen_restored_on_cancel_and_exception(self):
        for failure in (False, True):
            output = io.StringIO()
            state = TurnState()
            view = WorkView(Console(file=output, force_terminal=True, width=80, height=12), state)
            with patch.dict("os.environ", {"TERM": "xterm"}):
                try:
                    with view.monitor():
                        view.update_text("temporary preview")
                        state.cancel()
                        if failure:
                            raise RuntimeError("stop")
                except RuntimeError:
                    pass
            rendered = output.getvalue()
            self.assertEqual(rendered.count("\x1b[?1049h"), 1)
            self.assertEqual(rendered.count("\x1b[?1049l"), 1)
            self.assertNotIn("temporary preview", rendered.split("\x1b[?1049l", 1)[1])

    def test_stream_final_markdown_once_after_alternate_screen_closes(self):
        import importlib
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"HOME": home, "TERM": "xterm"}):
            app = importlib.import_module("main")
            output = io.StringIO()
            console = Console(file=output, force_terminal=True, width=80, height=12)
            state, response = TurnState(), Mock()
            events = [{"type": "text", "content": "FINAL_"},
                      {"type": "text", "content": "RESPONSE_UNIQUE"}]
            with patch.object(app, "console", console), patch.object(app, "iter_stream_events", return_value=iter(events)):
                self.assertEqual(app.display_stream_response(response, False, state), ("FINAL_RESPONSE_UNIQUE", []))
            rendered = output.getvalue()
            self.assertIn("\x1b[?1049h", rendered)
            normal = rendered.split("\x1b[?1049l", 1)[1]
            self.assertEqual(normal.count("FINAL_RESPONSE_UNIQUE"), 1)
            response.close.assert_called_once()

    def test_cancelled_stream_never_prints_partial_or_late_final_answer(self):
        import importlib
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"HOME": home, "TERM": "xterm"}):
            app = importlib.import_module("main")
            output = io.StringIO()
            console = Console(file=output, force_terminal=True, width=80, height=12)
            state, response = TurnState(), Mock()
            def events():
                yield {"type": "text", "content": "PARTIAL_UNIQUE"}
                state.cancel()
                yield {"type": "text", "content": "LATE_UNIQUE"}
            with patch.object(app, "console", console), patch.object(app, "iter_stream_events", return_value=events()):
                self.assertEqual(app.display_stream_response(response, False, state), ("", []))
            normal = output.getvalue().split("\x1b[?1049l", 1)[1]
            self.assertNotIn("PARTIAL_UNIQUE", normal)
            self.assertNotIn("LATE_UNIQUE", normal)
            response.close.assert_called_once()

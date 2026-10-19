import importlib
import io
import json
import os
import tempfile
import unittest
from contextlib import nullcontext
from unittest.mock import patch


class StreamDisplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"HOME": home}):
            cls.app = importlib.import_module("main")

    def test_first_fragment_is_rendered_before_next_event_arrives(self):
        output = io.StringIO()

        class FakeStatus:
            def start(self):
                pass

            def stop(self):
                pass

        class SlowResponse:
            def iter_lines(self):
                yield self.event("text", "**Первый")
                if output.getvalue() != "**Первый":
                    raise AssertionError("Первый фрагмент не показан до второго события")
                yield self.event("text", " фрагмент**")

            @staticmethod
            def event(event_type, content):
                return ("data: " + json.dumps({"type": event_type, "content": content})
                        ).encode("utf-8")

        with patch.object(self.app.console, "status", return_value=FakeStatus()), \
                patch.object(self.app.sys, "stdout", output):
            answer, calls = self.app.display_stream_response(SlowResponse(), False)

        self.assertEqual(output.getvalue(), "**Первый фрагмент**\n")
        self.assertEqual(answer, "**Первый фрагмент**")
        self.assertEqual(calls, [])

    def test_long_response_is_written_once_without_cursor_controls(self):
        output = io.StringIO()
        fragments = [f"Строка {number}\n" for number in range(100)]

        class FakeStatus:
            def start(self):
                pass

            def stop(self):
                pass

        class Response:
            def iter_lines(self):
                for fragment in fragments:
                    yield ("data: " + json.dumps({"type": "text", "content": fragment})
                           ).encode("utf-8")

        with patch.object(self.app.console, "status", return_value=FakeStatus()), \
                patch.object(self.app.sys, "stdout", output):
            answer, calls = self.app.display_stream_response(Response(), False)

        self.assertEqual(output.getvalue(), "".join(fragments))
        self.assertEqual(answer, "".join(fragments))
        self.assertEqual(calls, [])
        self.assertNotIn("\x1b", output.getvalue())

    def test_terminal_preview_is_replaced_by_single_final_markdown(self):
        output = io.StringIO()
        rendered = []

        from rich.console import Console
        from gemini_cli.client.work_view import WorkView
        from gemini_cli.runtime.turn import TurnState
        state = TurnState()
        state.view = WorkView(Console(file=io.StringIO(), force_terminal=True), state)

        class Response:
            def iter_lines(self):
                yield b'data: {"type": "text", "content": "**Hello"}'
                if state.view.text != "**Hello":
                    raise AssertionError("Потоковый фрагмент не виден")
                yield b'data: {"type": "text", "content": " world**"}'

        fake_console = Console(file=io.StringIO(), force_terminal=True)
        with patch.dict(os.environ, {"TERM": "xterm"}), \
                patch.object(self.app, "console", fake_console), \
                patch.object(fake_console, "print", side_effect=rendered.append), \
                patch.object(state.view, "screen", nullcontext), \
                patch.object(self.app.sys, "stdout", output):
            answer, calls = self.app.display_stream_response(Response(), False, state)

        self.assertEqual(answer, "**Hello world**")
        self.assertEqual(calls, [])
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(len(rendered), 1)
        self.assertIsInstance(rendered[0], self.app.Markdown)
        self.assertEqual(rendered[0].markup, answer)

    def test_cancelled_or_failed_preview_is_not_printed_as_final_answer(self):
        from rich.console import Console
        from gemini_cli.backends.base import StreamResult
        from gemini_cli.client.work_view import WorkView
        from gemini_cli.runtime.turn import TurnState
        for ending in ("cancel", "error"):
            with self.subTest(ending=ending):
                state = TurnState()
                console = Console(file=io.StringIO(), force_terminal=True)
                state.view = WorkView(console, state)
                def events():
                    yield {"type": "text", "content": "partial"}
                    if ending == "cancel":
                        state.cancel()
                    else:
                        yield {"type": "error", "content": "failed"}
                with patch.dict(os.environ, {"TERM": "xterm"}), \
                        patch.object(self.app, "console", console), \
                        patch.object(console, "print") as printed, \
                        patch.object(state.view, "screen", nullcontext):
                    result = self.app.display_stream_response(StreamResult(events=events()), False, state)
                self.assertEqual(result, ("", []))
                self.assertFalse(any(isinstance(call.args[0], self.app.Markdown)
                                     for call in printed.call_args_list))


if __name__ == "__main__":
    unittest.main()

import importlib
import io
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
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

    def test_terminal_preview_is_replaced_by_final_markdown(self):
        output = io.StringIO()
        rendered = []

        class FakeStatus:
            def start(self):
                pass

            def stop(self):
                pass

        class FakeConsole:
            is_terminal = True
            is_dumb_terminal = False
            legacy_windows = False
            in_screen = False

            @contextmanager
            def screen(self):
                self.in_screen = True
                try:
                    yield
                finally:
                    self.in_screen = False

            def status(self, *_args, **_kwargs):
                return FakeStatus()

            def print(self, value):
                rendered.append((self.in_screen, value))

        class Response:
            def iter_lines(self):
                yield b'data: {"type": "text", "content": "**Hello"}'
                if output.getvalue() != "**Hello":
                    raise AssertionError("Потоковый фрагмент не виден")
                yield b'data: {"type": "text", "content": " world**"}'

        fake_console = FakeConsole()
        with patch.object(self.app, "console", fake_console), \
                patch.object(self.app.sys, "stdout", output):
            answer, calls = self.app.display_stream_response(Response(), False)

        self.assertEqual(answer, "**Hello world**")
        self.assertEqual(calls, [])
        self.assertEqual(output.getvalue(), "**Hello world**\n")
        self.assertEqual(len(rendered), 1)
        self.assertFalse(rendered[0][0])
        self.assertIsInstance(rendered[0][1], self.app.Markdown)
        self.assertEqual(rendered[0][1].markup, answer)


if __name__ == "__main__":
    unittest.main()

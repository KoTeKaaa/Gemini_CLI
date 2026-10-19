import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch
from prompt_toolkit.data_structures import Size
from prompt_toolkit.keys import Keys
from prompt_toolkit.key_binding.key_processor import KeyPress
from gemini_cli.client.process import ProcessLog
from gemini_cli.client.sessions import attach, session_command


class SessionRelayTests(unittest.TestCase):
    def test_log_cursor_is_incremental_and_bounded(self):
        log = ProcessLog(8)
        log.append("abcd")
        cursor, text = log.read_since(0)
        self.assertEqual((cursor, text), (4, "abcd"))
        self.assertEqual(log.read_since(cursor), (4, ""))
        log.append("efghijkl")
        self.assertEqual(log.read_since(cursor), (12, "efghijkl"))
        self.assertIn("Начало вывода удалено", log.read_since(0)[1])

    def test_native_output_is_not_parsed_or_replayed_each_tick(self):
        log = ProcessLog()
        controls = "\x1b]2;title\a\x1b]7;file://host/dir\a\x1b[?2004h\x1b[31mprompt\x1b[0m\r\n"
        log.append(controls)
        process = Mock(stdout=log, poll=Mock(return_value=None))
        source, output = Mock(closed=False), Mock()
        source.raw_mode.return_value = nullcontext()
        source.read_keys.side_effect = [[], [KeyPress(Keys.Left, "\x1b[D"),
            KeyPress(Keys.ControlM, "\r"), KeyPress(Keys.BracketedPaste, "текст\n")],
            [KeyPress(Keys.ControlSquareClose, "\x1d")]]
        source.flush_keys.return_value = []
        output.get_size.return_value = Size(rows=30, columns=100)
        with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
             patch("prompt_toolkit.input.create_input", return_value=source), \
             patch("gemini_cli.client.sessions.terminal_output", return_value=nullcontext()), \
             patch("prompt_toolkit.output.create_output", return_value=output):
            attach(process)
        values = [call.args[0] for call in output.write_raw.call_args_list]
        self.assertEqual(values.count(controls), 1)
        self.assertTrue(values[-1].endswith("\x1b[?1049l"))
        process.resize.assert_called_once_with(30, 100)
        self.assertEqual([call.args[0] for call in process.write.call_args_list],
                         ["\x1b[D", "\r", "\x1b[200~текст\n\x1b[201~"])
        source.close.assert_called_once()

    def test_missing_name_shows_explanation_without_starting_a_process(self):
        manager, notify = Mock(), Mock()
        session_command(manager, "/session start", ".", notify)
        message = notify.call_args.args[0]
        self.assertIn("/session start build", message)
        self.assertIn("Ctrl+]", message)
        self.assertIn("сохранив процесс", message)
        self.assertIn("закрытии CLI", message)
        manager.start.assert_not_called()

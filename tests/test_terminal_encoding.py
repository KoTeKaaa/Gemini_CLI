import io
import unittest
from unittest.mock import Mock

from gemini_cli.client.terminal import configure_output


class TerminalEncodingTest(unittest.TestCase):
    def test_redirected_windows_output_supports_russian(self):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="cp1252")
        self.addCleanup(stream.close)
        configure_output(platform="nt", streams=[stream])
        stream.write("Ошибка соединения")
        stream.flush()
        self.assertEqual(buffer.getvalue().decode("utf-8"), "Ошибка соединения")

    def test_native_console_and_other_platforms_keep_their_configuration(self):
        stream = Mock()
        stream.isatty.return_value = True
        configure_output(platform="nt", streams=[stream])
        stream.reconfigure.assert_not_called()
        stream.isatty.return_value = False
        configure_output(platform="posix", streams=[stream])
        stream.reconfigure.assert_not_called()

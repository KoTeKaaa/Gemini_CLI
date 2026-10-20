import unittest
from unittest.mock import Mock
from gemini_cli.client.clipboard import ClipboardError
from gemini_cli.client.clipboard_windows import WindowsClipboard
from tests.test_draft import png


class WindowsClipboardTest(unittest.TestCase):
    def test_only_explicit_read(self):
        reader = Mock(return_value=('PNG', png()))
        clipboard = WindowsClipboard(reader)
        reader.assert_not_called()
        self.assertEqual(clipboard.read_image().data, png())
        reader.assert_called_once_with()

    def test_text_empty_file_list_and_locked(self):
        self.assertIsNone(WindowsClipboard(lambda: None).read_image())
        for message in ('список файлов', 'занят'):
            with self.assertRaisesRegex(ClipboardError, message):
                WindowsClipboard(Mock(side_effect=ClipboardError(message))).read_image()

    def test_invalid_bytes(self):
        with self.assertRaises(ClipboardError):
            WindowsClipboard(lambda: ('PNG', b'invalid')).read_image()

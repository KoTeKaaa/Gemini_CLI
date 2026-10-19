import sys
import unittest
from unittest.mock import Mock
from gemini_cli.client.clipboard import ClipboardError
from gemini_cli.client.clipboard_linux import LinuxClipboard, bounded_output
from tests.test_draft import png


class LinuxClipboardTest(unittest.TestCase):
    def test_wayland_and_x11(self):
        for backend, executable in [('wayland', 'wl-paste'), ('x11', 'xclip')]:
            run = Mock(side_effect=[b'image/png\ntext/plain', png()])
            self.assertEqual(LinuxClipboard(backend, run).read_image().data, png())
            self.assertEqual(run.call_args_list[0].args[0][0], executable)

    def test_text_and_files(self):
        self.assertIsNone(LinuxClipboard('wayland', Mock(return_value=b'text/plain')).read_image())
        with self.assertRaisesRegex(ClipboardError, 'список файлов'):
            LinuxClipboard('x11', Mock(return_value=b'text/uri-list')).read_image()

    def test_process_output_and_timeout_are_bounded(self):
        with self.assertRaisesRegex(ClipboardError, 'размер'):
            bounded_output([sys.executable, '-c', 'print("a"*10000)'], limit=8)
        with self.assertRaisesRegex(ClipboardError, 'секунды'):
            bounded_output([sys.executable, '-c', 'import time; time.sleep(5)'], limit=8, timeout=.05)
        with self.assertRaises(ClipboardError):
            bounded_output(['/nonexistent-clipboard-program'], limit=8)

    def test_invalid_image(self):
        with self.assertRaises(ClipboardError):
            LinuxClipboard('wayland', Mock(side_effect=[b'image/png', b'bad'])).read_image()

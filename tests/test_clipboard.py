import unittest
from unittest.mock import Mock

from gemini_cli.client.clipboard import ClipboardError, detect_backend


class ClipboardDetectionTest(unittest.TestCase):
    def test_detection_does_not_read_clipboard(self):
        which = Mock(return_value='/usr/bin/wl-paste')
        self.assertEqual(detect_backend(platform='linux', environ={'WAYLAND_DISPLAY': 'w'}, which=which), 'wayland')
        which.assert_called_once_with('wl-paste')
        self.assertEqual(detect_backend(platform='win32', environ={}, which=which), 'windows')

    def test_missing_wayland_does_not_fall_back_to_x11(self):
        with self.assertRaisesRegex(ClipboardError, 'wl-clipboard'):
            detect_backend(platform='linux', environ={'WAYLAND_DISPLAY': 'w', 'DISPLAY': ':0'}, which=lambda _: None)

    def test_x11_and_headless(self):
        self.assertEqual(detect_backend(platform='linux', environ={'DISPLAY': ':0'}, which=lambda _: 'xclip'), 'x11')
        with self.assertRaises(ClipboardError):
            detect_backend(platform='linux', environ={}, which=lambda _: None)

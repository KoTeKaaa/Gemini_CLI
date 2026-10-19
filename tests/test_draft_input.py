import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from gemini_cli.client.draft import Draft
from gemini_cli.client.input import DraftInput
from gemini_cli.client.clipboard import ClipboardImage, ClipboardError
from tests.test_draft import png


class DraftInputTest(unittest.TestCase):
    def test_key_retains_text_without_sending(self):
        draft = Draft()
        reader = Mock()
        reader.read_image.return_value = ClipboardImage(png())
        ui = DraftInput(draft, lambda: reader)
        event = SimpleNamespace(current_buffer=SimpleNamespace(text='keep\ntext'), app=Mock())
        ui.paste_key(event)
        self.assertEqual(draft.text, 'keep\ntext')
        self.assertEqual(len(draft.images), 1)
        self.assertIn('Скриншот', ui.status())
        event.app.invalidate.assert_called_once()
        self.assertTrue(ui.command('/remove 1'))
        self.assertEqual(draft.images, [])

    def test_failure_and_commands(self):
        draft = Draft('keep')
        reader = Mock()
        reader.read_image.side_effect = ClipboardError('занят')
        ui = DraftInput(draft, lambda: reader)
        self.assertTrue(ui.command('/paste'))
        self.assertEqual(draft.text, 'keep')
        self.assertEqual(draft.images, [])
        self.assertIn('занят', ui.status())
        self.assertTrue(ui.command('/remove 0'))
        self.assertFalse(ui.command('/help'))

    def test_ctrl_v_text_uses_buffer_insertion(self):
        reader = Mock()
        reader.read_image.return_value = None
        reader.read_text.return_value = 'a\nb'
        ui = DraftInput(Draft('keep'), lambda: reader)
        buffer = Mock(text='keep')
        ui.paste_key(SimpleNamespace(current_buffer=buffer, app=Mock()))
        buffer.insert_text.assert_called_once_with('a\nb')
        self.assertEqual(ui.draft.images, [])

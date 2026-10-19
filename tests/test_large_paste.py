import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from prompt_toolkit.buffer import Buffer
from gemini_cli.client.draft import Draft
from gemini_cli.client.input import DraftInput


class LargePasteTest(unittest.TestCase):
    def test_exact_newlines_multiple_blocks_and_delete(self):
        draft = Draft()
        ui = DraftInput(draft)
        buffer = Buffer()
        buffer.insert_text('before ')
        text = ('a\r\nb\nc\r' * 100)
        ui.bracketed_paste(SimpleNamespace(current_buffer=buffer, data=text, app=Mock()))
        self.assertLess(len(buffer.text), 50)
        self.assertEqual(draft.message(buffer.text), 'before ' + text)
        ui.insert(buffer, 'x' * 700)
        draft.text = buffer.text
        self.assertEqual(len(draft.pastes), 2)
        self.assertTrue(ui.command('/paste-remove 1'))
        self.assertEqual(draft.message(draft.text), 'before ' + 'x' * 700)

    def test_edit_show_and_small_paste(self):
        draft = Draft()
        ui = DraftInput(draft)
        buffer = Buffer()
        ui.insert(buffer, 'x' * 700)
        draft.text = buffer.text
        with patch('gemini_cli.client.input.edit_text', return_value='edited\r\n') as edit:
            ui.command('/paste-edit 1')
            edit.assert_called_once_with('x' * 700)
        self.assertEqual(draft.message(buffer.text), 'edited\r\n')
        with patch('gemini_cli.client.input.view_text') as show:
            ui.command('/paste-show 1')
            show.assert_called_once_with('edited\r\n')
        ui.insert(buffer, 'small')
        self.assertTrue(buffer.text.endswith('small'))

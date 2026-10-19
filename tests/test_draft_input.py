import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
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

    def test_malformed_commands_are_consumed_without_changing_draft(self):
        draft = Draft('keep')
        ui = DraftInput(draft, Mock(side_effect=AssertionError('clipboard accessed')))
        for action in ('/paste-show', '/paste-edit', '/paste-remove', '/remove', '/remove-file'):
            for suffix in ('', ' ', '\t', ' nope', ' 1 extra', ' 0'):
                with self.subTest(command=action + suffix):
                    self.assertTrue(ui.command(action + suffix))
                    self.assertIn('Вложений нет', ui.notice)
                    self.assertEqual(draft.text, 'keep')
        for action in ('/paste', '/attachments'):
            self.assertTrue(ui.command(action + ' extra'))
            self.assertIn('Использование:', ui.notice)

    def test_shared_remove_and_stable_numbers(self):
        draft = Draft('keep')
        draft.add_text_file('LICENSE:1-20', 'lines')
        draft.add_image('screen.png', png())
        block = draft.add_paste('long')
        draft.text += block.token
        ui = DraftInput(draft)
        ui.command('/attachments')
        self.assertIn('#1 — файл LICENSE:1-20', ui.notice)
        self.assertIn('#2 — изображение', ui.notice)
        self.assertIn('#3 — вставка', ui.notice)
        ui.command('/remove 1')
        self.assertEqual(draft.files, [])
        self.assertIn('Удалено #1', ui.take_notice())
        self.assertNotIn('Удалено', ui.status())
        ui.command('/remove #3')
        self.assertEqual(draft.text, 'keep')
        ui.command('/remove')  # Единственное оставшееся вложение выбирается автоматически.
        self.assertEqual(draft.items(), [])
        self.assertIn('Удалено #2', ui.notice)

    def test_edit_single_file_and_select_from_multiple(self):
        draft = Draft()
        draft.add_text_file('LICENSE', 'original')
        ui = DraftInput(draft)
        with patch('gemini_cli.client.input.edit_text', return_value='edited'):
            ui.command('/edit')
        self.assertEqual(draft.files, [('LICENSE', 'edited')])
        self.assertIn('Изменено #1', ui.notice)
        draft.add_paste('block')
        ui.command('/remove')
        self.assertIn('Выберите номер: /remove 1', ui.notice)
        self.assertEqual(len(draft.items()), 2)
        ui.command('/remove 9')
        ui.command('/attachments')
        self.assertNotIn('Нет вложения #9', ui.notice)
        self.assertNotIn('Нет вложения #9', ui.take_notice())
        self.assertNotIn('LICENSE', ui.status())  # Полный список не дублируется в toolbar.

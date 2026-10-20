from io import BytesIO
import unittest
from unittest.mock import patch
from PIL import Image
from gemini_cli.client.draft import Draft
from gemini_cli.protocol.attachments import ImageAttachment, MAX_IMAGE_BYTES


def png():
    stream = BytesIO()
    Image.new('RGB', (2, 3)).save(stream, format='PNG')
    return stream.getvalue()


class DraftTest(unittest.TestCase):
    def test_multiple_remove_and_text_preserved(self):
        draft = Draft('Текст\r\nстрока')
        one = draft.add_image('one.png', png())
        two = draft.add_image('two.png', png())
        draft.remove(one.id)
        self.assertEqual(draft.images, [two])
        self.assertEqual(draft.text, 'Текст\r\nстрока')
        self.assertNotIn('data', two.metadata())
        self.assertNotIn(str(two.data), repr(two))

    def test_invalid_and_byte_limit(self):
        for data in (b'', b'bad', b'x' * (MAX_IMAGE_BYTES + 1)):
            with self.assertRaises(ValueError):
                ImageAttachment('bad.png', data)

    def test_pixel_limit_and_count_are_atomic(self):
        draft = Draft('keep')
        with patch('gemini_cli.protocol.attachments.MAX_PIXELS', 1):
            with self.assertRaises(ValueError):
                draft.add_image('big.png', png())
        self.assertEqual(draft.images, [])
        for _ in range(4):
            draft.add_image('small.png', png())
        with self.assertRaises(ValueError):
            draft.add_image('extra.png', png())
        self.assertEqual(len(draft.images), 4)
        self.assertEqual(draft.text, 'keep')

    def test_one_number_sequence_preserves_identity_after_removal(self):
        draft = Draft('keep')
        draft.add_text_file('LICENSE:1-20', 'selected lines')
        image = draft.add_image('screen.png', png())
        block = draft.add_paste('long text')
        self.assertEqual([number for number, _ in draft.items()], [1, 2, 3])
        draft.text += block.token
        draft.remove_number(1)
        self.assertEqual(draft.images, [image])
        self.assertEqual([number for number, _ in draft.items()], [2, 3])
        draft.remove_number(3)
        self.assertEqual(draft.text, 'keep')
        self.assertEqual(draft.pastes, [])
        with self.assertRaisesRegex(ValueError, 'Нет вложения #1'):
            draft.remove_number(1)
        draft.clear()
        draft.add_text_file('next', 'text')
        self.assertEqual([number for number, _ in draft.items()], [1])

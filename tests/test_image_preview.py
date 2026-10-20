import os
from pathlib import Path
import unittest
from unittest.mock import patch
from gemini_cli.client.preview import ImagePreview
from gemini_cli.client.draft import Draft
from gemini_cli.client.input import DraftInput
from tests.test_draft import png


class ImagePreviewTest(unittest.TestCase):
    def test_file_is_private_and_removed_with_attachment(self):
        draft = Draft()
        image = draft.add_image('screen.png', png())
        ui = DraftInput(draft)
        self.addCleanup(ui.close)
        self.assertIsNone(ui.preview.directory)
        with patch('gemini_cli.client.preview.open_external') as opened:
            ui.command('/paste-show')
        path = opened.call_args.args[0]
        self.assertEqual(path.read_bytes(), image.data)
        if os.name != 'nt':
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        ui.command('/remove 1')
        ui.take_notice()
        self.assertFalse(path.exists())

    def test_open_error_cleans_bytes_and_does_not_change_draft(self):
        draft = Draft()
        image = draft.add_image('screen.png', png())
        ui = DraftInput(draft)
        self.addCleanup(ui.close)
        with patch('gemini_cli.client.preview.open_external', side_effect=OSError('private filename')):
            ui.command('/show 1')
        self.assertIn('Не удалось', ui.notice)
        self.assertNotIn('private filename', ui.notice)
        self.assertEqual(draft.images, [image])
        self.assertEqual(list(Path(ui.preview.directory.name).iterdir()), [])

    def test_close_cleans_temporary_directory(self):
        preview = ImagePreview()
        draft = Draft()
        image = draft.add_image('screen.png', png())
        with patch('gemini_cli.client.preview.open_external'):
            preview.show(image)
        directory = Path(preview.directory.name)
        preview.close()
        self.assertFalse(directory.exists())

    def test_locked_viewer_file_reports_cleanup_directory(self):
        preview = ImagePreview()
        draft = Draft()
        image = draft.add_image('screen.png', png())
        with patch('gemini_cli.client.preview.open_external'):
            preview.show(image)
        temporary = preview.directory
        with patch.object(temporary, 'cleanup'), patch.object(Path, 'unlink', side_effect=PermissionError('locked')):
            warning = preview.close()
        self.assertIn(temporary.name, warning)
        temporary.cleanup()

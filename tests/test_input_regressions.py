import importlib
import os
import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
from gemini_cli.client.completion import allowed_path
from gemini_cli.protocol.attachments import ImageAttachment
from gemini_cli.protocol.images import encode_images
from PIL import Image
from io import BytesIO


class InputRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}):
            cls.app = importlib.import_module('main')

    def test_image_size_does_not_remove_tools(self):
        output = BytesIO()
        Image.frombytes('RGB', (300, 300), os.urandom(300 * 300 * 3)).save(output, format='PNG')
        images = encode_images([ImageAttachment('screen.png', output.getvalue())])
        row = {'role': 'user', 'content': 'look', 'images': images}
        payload = self.app.build_stream_payload([row], None, 'gemini-3.5-flash-lite', True)
        self.assertIn('execute_command', payload['supported_tools'])
        later = self.app.build_stream_payload([row, {'role': 'user', 'content': 'read code'}], None, 'gemini-3.5-flash-lite', True)
        self.assertIn('execute_command', later['supported_tools'])

    def test_oversized_draft_stays_editable_and_does_not_send(self):
        backend = Mock(mode='local')
        with patch.object(self.app, 'show_chat_menu', return_value=(None, True)), \
             patch.object(self.app, 'PromptSession') as session, \
             patch.object(self.app, 'print_banner'), patch.object(self.app.console, 'print'):
            session.return_value.prompt.side_effect = ['x' * 28001, 'exit']
            self.app.main(backend)
            self.assertEqual(session.return_value.prompt.call_count, 2)
            self.assertEqual(session.return_value.prompt.call_args.kwargs['default'], 'x' * 28001)
            backend.stream_chat.assert_not_called()

    def test_network_failure_preserves_draft(self):
        backend = Mock(mode='remote')
        backend.stream_chat.side_effect = ConnectionError('sensitive request')
        with patch.object(self.app, 'show_chat_menu', return_value=(None, True)), \
             patch.object(self.app, 'PromptSession') as session, \
             patch.object(self.app, 'print_banner'), patch.object(self.app.console, 'print') as printed:
            session.return_value.prompt.side_effect = ['hello', 'exit']
            self.app.main(backend)
            self.assertEqual(session.return_value.prompt.call_args.kwargs['default'], 'hello')
            self.assertNotIn('sensitive request', str(printed.call_args_list))

    def test_symlink_alias_does_not_expose_hidden_directory(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            (base / '.aws').mkdir()
            (base / '.aws' / 'credentials').write_text('secret')
            try:
                (base / 'public').symlink_to(base / '.aws' / 'credentials')
            except OSError:
                self.skipTest('symlinks unavailable')
            self.assertIsNone(allowed_path(root, 'public'))

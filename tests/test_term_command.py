import importlib
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from gemini_cli.client.completion import COMMANDS
from gemini_cli.client.draft import Draft


class TermCommandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}):
            cls.app = importlib.import_module('main')

    def test_term_preserves_draft_attachments_and_backend_in_both_chat_modes(self):
        self.assertIn('/term', COMMANDS)
        for mode in ['local', 'remote']:
            for selection in [(None, True), ('persistent-chat', False)]:
                with self.subTest(mode=mode, chat=selection), tempfile.TemporaryDirectory() as root:
                    backend = Mock(mode=mode)
                    draft = Draft(text='unfinished message')
                    draft.add_text_file('test.txt', 'attachment')
                    before = draft.items()
                    with patch.object(self.app, 'show_chat_menu', return_value=selection), \
                         patch.object(self.app, 'Draft', return_value=draft), \
                         patch.object(self.app, 'PromptSession') as session, \
                         patch.object(self.app, 'print_banner'), \
                         patch.object(self.app.console, 'print'), \
                         patch.object(self.app, 'launch_shell', side_effect=[root, None, ValueError('TTY')]) as launch:
                        session.return_value.prompt.side_effect = [
                            '/term extra', '/term', '/term', '/term', 'exit']
                        self.app.main(backend)
                        self.assertEqual(launch.call_count, 3)
                        self.assertEqual(launch.call_args_list[1].args, (root,))
                        self.assertEqual(launch.call_args_list[2].args, (root,))
                        self.assertEqual(draft.text, 'unfinished message')
                        self.assertEqual(draft.items(), before)
                        self.assertTrue(all(call.kwargs['default'] == draft.text
                                            for call in session.return_value.prompt.call_args_list))
                        backend.stream_chat.assert_not_called()
                        backend.delete_chat.assert_not_called()
                        self.assertTrue(all('›' in str(call.args[0])
                                            for call in session.return_value.prompt.call_args_list))


if __name__ == '__main__':
    unittest.main()

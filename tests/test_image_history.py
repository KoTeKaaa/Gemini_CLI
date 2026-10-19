import json
import tempfile
import unittest
from pathlib import Path
from gemini_cli.client.draft import Draft
from gemini_cli.client.local_chats import LocalChats
from gemini_cli.runtime.attachments import attachment_text, restore_images, missing_image_note
from gemini_cli.protocol.images import encode_images
import importlib
import os
from unittest.mock import patch
from tests.test_draft import png


class ImageHistoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}):
            cls.app = importlib.import_module('main')

    def test_bytes_not_in_sqlite_and_restore_requires_live_memory(self):
        draft = Draft('hello')
        draft.add_image('screen', png())
        text = attachment_text(draft.text, draft.images)
        row = {'role': 'user', 'content': text, 'images': encode_images(draft.images)}
        with tempfile.TemporaryDirectory() as root:
            store = LocalChats(Path(root))
            chat = store.create('title')['id']
            store.append(chat, [row])
            stored = store.read(chat)
            self.assertNotIn(row['images'][0]['data'], json.dumps(stored))
            self.assertNotIn('images', stored[0])
            self.assertIn('повторно', missing_image_note(stored[0]))
            self.assertEqual(restore_images(stored, [row])[0]['images'], row['images'])
            self.assertEqual(restore_images(stored, []), stored)
            store.close()

    def test_image_sent_in_persistent_initial_and_continuation(self):
        draft = Draft('look')
        draft.add_image('screen', png())
        row = {'role': 'user', 'content': attachment_text(draft.text, draft.images),
               'images': encode_images(draft.images)}
        initial = self.app.build_stream_payload([row], 'chat', 'gemini-3.5-flash-lite', False)
        self.assertEqual(initial['images'], row['images'])
        history = [row, {'role': 'tool', 'content': 'result', 'name': 'read_local_files'}]
        continuation = self.app.build_stream_payload(history, 'chat', 'gemini-3.5-flash-lite', False)
        self.assertEqual(continuation['history'][0]['images'], row['images'])
        following = self.app.build_stream_payload([row, {'role': 'user', 'content': 'again'}], 'chat', 'gemini-3.5-flash-lite', False)
        self.assertEqual(following['history'], [row])

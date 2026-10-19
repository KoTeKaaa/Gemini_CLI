import json
import tempfile
import unittest
from pathlib import Path
from gemini_cli.client.draft import Draft
from gemini_cli.client.local_chats import LocalChats
from gemini_cli.runtime.attachments import attachment_text, restore_images, missing_image_note
from gemini_cli.protocol.images import encode_images
from gemini_cli.protocol.attachments import ImageAttachment
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

    def test_both_backends_preserve_image_followup_without_persisting_bytes(self):
        from types import SimpleNamespace
        from gemini_cli.backends.local import LocalBackend
        from tests.test_tool_continuation import FakeDb
        with patch.dict(os.environ, {'API_KEY': 'test', 'SUPABASE_URL': 'https://example.supabase.co',
                                     'SUPABASE_ANON_KEY': 'test'}):
            server = importlib.import_module('server')
        draft = Draft('  look\r\n')
        draft.add_image('screen', png())
        row = {'role': 'user', 'content': attachment_text(draft.text, draft.images),
               'images': encode_images(draft.images)}
        for mode in ('local', 'remote'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                seen = []
                def stream(provider, **kwargs):
                    seen.append(kwargs['contents'])
                    yield {'type': 'text', 'content': 'ok'}
                if mode == 'local':
                    backend = LocalBackend('test', Path(root), provider=object())
                    chat_id = backend.create_chat('images')['id']
                    send = lambda payload: list(backend.stream_chat(payload).events)
                    read = lambda: backend.chats.read(chat_id)
                    patches = [patch('gemini_cli.backends.local.stream_events', stream)]
                else:
                    db = FakeDb()
                    chat_id = 'chat-1'
                    user = server.UserContext('user-1', db)
                    def send(payload):
                        return list(server.stream_chat(server.StreamChatPayload(**payload), user).body_iterator)
                    read = lambda: db.messages
                    patches = [patch.object(server, 'stream_events', stream),
                               patch.object(server, 'require_subscription', return_value={'features': list(server.TOOLS)}),
                               patch.object(server, 'reserve_request'),
                               patch.object(server, 'StreamingResponse', side_effect=lambda source, **kw: SimpleNamespace(body_iterator=source))]
                from contextlib import ExitStack
                with ExitStack() as stack:
                    for item in patches:
                        stack.enter_context(item)
                    send(self.app.build_stream_payload([row], chat_id, 'gemini-3.5-flash-lite', False))
                    send(self.app.build_stream_payload([row, {'role': 'user', 'content': 'again'}], chat_id, 'gemini-3.5-flash-lite', False))
                    self.assertTrue(any(part.inline_data for msg in seen[-1] for part in msg.parts))
                    self.assertEqual(read()[0]['content'], row['content'])
                    self.assertNotIn(row['images'][0]['data'], json.dumps(read()))
                    send({'message': 'after restart', 'chat_id': chat_id, 'supported_tools': []})
                    self.assertFalse(any(part.inline_data for msg in seen[-1] for part in msg.parts))
                    self.assertTrue(any('повторно' in (part.text or '') for msg in seen[-1] for part in msg.parts))
                if mode == 'local':
                    backend.close()

    def test_context_image_count_is_bounded(self):
        from gemini_cli.runtime.attachments import bound_image_history
        from gemini_cli.protocol.images import validate_payload_images
        images = encode_images([ImageAttachment('screen', png())])
        rows = [{'role': 'user', 'content': str(i), 'images': images} for i in range(5)]
        with self.assertRaises(ValueError):
            validate_payload_images({'history': rows})
        bound_image_history(rows)
        self.assertNotIn('images', rows[0])
        self.assertTrue(validate_payload_images({'history': rows}))

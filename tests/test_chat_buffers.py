import copy
import unittest
from unittest.mock import patch

from gemini_cli.client.chat_buffers import ChatBuffers, filter_chats
from gemini_cli.client.draft import Draft
from gemini_cli.runtime.turn import TurnState


class ChatBuffersTests(unittest.TestCase):
    def setUp(self):
        self.buffers = ChatBuffers()

    def test_draft_history_and_summary_are_independent_snapshots(self):
        draft = Draft('draft')
        paste = draft.add_paste('large pasted text')
        draft.text += paste.token
        draft.add_text_file('file.txt', 'text file contents')
        with patch('gemini_cli.protocol.attachments.image_details', return_value=('image/png', 1, 1)):
            image = draft.add_image('image.png', b'image bytes')
        history = [{'role': 'user', 'content': 'sent', 'images': [{'data': b'sent bytes'}]}]
        summary = {'text': 'summary', 'boundary_id': 'event-1'}
        self.buffers.save('local-profile', 'chat', history, draft, summary)
        history.clear()
        summary.clear()
        draft.clear()
        restored = self.buffers.restore('local-profile', 'chat')
        self.assertEqual(restored['history'][0]['content'], 'sent')
        self.assertEqual(restored['summary']['boundary_id'], 'event-1')
        self.assertEqual(restored['draft'].images[0].id, image.id)
        self.assertEqual(restored['draft'].images[0].data, b'image bytes')
        self.assertEqual(restored['draft'].files, [('file.txt', 'text file contents')])
        self.assertEqual(restored['draft'].pastes[0].text, 'large pasted text')
        number = restored['draft']._next_number
        self.assertEqual(restored['draft'].add_text_file('more', 'text'), number)
        restored['draft'].clear()
        restored['history'].clear()
        self.assertTrue(self.buffers.restore('local-profile', 'chat')['draft'].images)
        self.assertTrue(self.buffers.restore('local-profile', 'chat')['history'])

    def test_scope_and_chat_id_isolation(self):
        for scope, chat_id, text in [('local', None, 'temporary'), ('local', 'same', 'local'),
                                     ('remote-account', 'same', 'remote')]:
            self.buffers.save(scope, chat_id, [], Draft(text))
        self.assertEqual(self.buffers.restore('local', None)['draft'].text, 'temporary')
        self.assertEqual(self.buffers.restore('local', 'same')['draft'].text, 'local')
        self.assertEqual(self.buffers.restore('remote-account', 'same')['draft'].text, 'remote')
        self.assertIsNone(self.buffers.restore('other-account', 'same'))

    def test_recency_tracks_visits_not_saves(self):
        self.buffers.visit('scope', 'a')
        self.buffers.visit('scope', 'b')
        self.buffers.save('scope', 'c', [], Draft())
        self.assertEqual(self.buffers.recent_ids('scope'), ('b', 'a'))
        self.buffers.visit('scope', 'a')
        self.assertEqual(self.buffers.recent_ids('scope'), ('a', 'b'))
        self.assertIsNone(self.buffers.restore('other', 'missing'))
        self.assertEqual(self.buffers.recent_ids('other'), ())

    def test_clear_temporary_cancels_and_preserves_other_buffers(self):
        for scope, chat_id in [('local', None), ('local', 'permanent'), ('remote', None)]:
            self.buffers.save(scope, chat_id, [{'content': 'history'}], Draft('draft'), {'text': 'summary'})
        turn = TurnState()
        cleared = self.buffers.clear_temporary('local', turn)
        self.assertTrue(turn.cancelled.is_set())
        self.assertFalse(turn.accepts({}))
        self.assertEqual(cleared['history'], [])
        self.assertEqual(cleared['draft'].text, '')
        self.assertIsNone(cleared['summary'])
        self.assertEqual(self.buffers.restore('local', 'permanent')['draft'].text, 'draft')
        self.assertEqual(self.buffers.restore('remote', None)['draft'].text, 'draft')
        self.assertEqual(set(cleared), {'history', 'draft', 'summary'})

    def test_title_search_preserves_ids_and_stable_order(self):
        chats = [{'id': 'a', 'title': 'Same'}, {'id': 'b', 'title': 'Same'},
                 {'id': 'c', 'title': 'Другой'}, {'id': 'd', 'title': 'Same'}]
        original = copy.deepcopy(chats)
        result = filter_chats(chats, ' SAME ', 'b', ['d', 'd', 'a'])
        self.assertEqual([chat['id'] for chat in result], ['b', 'd', 'a'])
        self.assertTrue(result[0]['is_current'])
        self.assertFalse(result[1]['is_current'])
        self.assertEqual(filter_chats(chats, 'дру')[0]['id'], 'c')
        self.assertEqual(filter_chats(chats, 'missing'), [])
        self.assertEqual([chat['id'] for chat in filter_chats(chats, '')], ['a', 'b', 'c', 'd'])
        result[0]['title'] = 'mutated'
        self.assertEqual(chats, original)

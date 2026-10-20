from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from threading import Barrier
import unittest
from uuid import uuid4

from gemini_cli.client.local_chats import LocalChats


class LocalChatStateTests(unittest.TestCase):
    def test_two_instances_claim_once_and_completed_claim_never_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            first = LocalChats(Path(directory))
            second = LocalChats(Path(directory))
            chat = first.create('chat')['id']
            barrier = Barrier(2)
            def claim(store):
                barrier.wait()
                return store.claim_request(chat, 'request', 'turn')
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(claim, (first, second)))
            self.assertEqual(sorted(results), [False, True])
            first.update_request_status(chat, 'request', 'completed')
            self.assertFalse(LocalChats(Path(directory)).claim_request(chat, 'request', 'turn'))
            with self.assertRaises(ValueError):
                first.claim_request(chat, 'request', 'different-turn')
            other = first.create('other')['id']
            with self.assertRaises(ValueError):
                second.claim_request(other, 'request', 'turn')
            with self.assertRaises(LookupError):
                second.claim_request('missing', 'new-request', 'turn')
            isolated = LocalChats(Path(directory), 'other-profile')
            with self.assertRaises(LookupError):
                isolated.claim_request(chat, 'request', 'turn')

    def test_cancel_is_terminal_and_updates_running_messages_only(self):
        store = LocalChats(Path('/unused'), temporary=True)
        self.addCleanup(store.close)
        chat = store.create('chat')['id']
        store.claim_request(chat, 'request', 'turn')
        store.append(chat, [{'role': 'user', 'content': 'hello', 'turn_id': 'turn',
                            'request_id': 'request', 'status': 'running'}])
        store.update_request_status(chat, 'request', 'cancelled')
        store.update_request_status(chat, 'request', 'cancelled')
        self.assertEqual(store.read(chat)[0]['status'], 'cancelled')
        for status in ('completed', 'running', 'failed', 'invalid'):
            with self.subTest(status=status), self.assertRaises(ValueError):
                store.update_request_status(chat, 'request', status)
        with self.assertRaises(LookupError):
            store.update_request_status('missing', 'request', 'cancelled')
        with store.connection() as db:
            self.assertEqual(db.execute('select status from generation_requests').fetchone()[0], 'cancelled')
        self.assertFalse(store.claim_request(chat, 'request', 'turn'))

    def history(self, store, chat):
        rows = []
        for turn in range(3):
            for role in ('user', 'model'):
                rows.append({'id': str(uuid4()), 'role': role, 'content': f'{turn}:{role}',
                             'turn_id': str(turn), 'request_id': str(turn),
                             'event_index': int(role == 'model'), 'status': 'completed'})
        store.append(chat, rows)
        return rows

    def test_summary_is_owned_safe_monotonic_and_preserves_full_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = LocalChats(root)
            chat = store.create('chat')['id']
            rows = self.history(store, chat)
            before = store.read(chat)
            store.set_summary(chat, 'first summary', rows[1]['id'])
            store.set_summary(chat, 'second summary', rows[3]['id'])
            metadata = LocalChats(root).metadata(chat)
            self.assertEqual(metadata['summary'], 'second summary')
            self.assertEqual(metadata['summary_boundary'], rows[3]['id'])
            self.assertEqual(store.read(chat), before)
            for boundary in (rows[1]['id'], rows[2]['id'], rows[5]['id']):
                with self.subTest(boundary=boundary), self.assertRaises(ValueError):
                    store.set_summary(chat, 'unsafe', boundary)
            other = store.create('other')['id']
            with self.assertRaises(LookupError):
                store.set_summary(other, 'wrong chat', rows[1]['id'])
            with self.assertRaises(LookupError):
                LocalChats(root, 'other-profile').metadata(chat)
            self.assertEqual(store.metadata(chat)['summary'], 'second summary')

    def test_summary_rejects_partial_turn_and_legacy_boundary(self):
        store = LocalChats(Path('/unused'), temporary=True)
        self.addCleanup(store.close)
        chat = store.create('chat')['id']
        rows = self.history(store, chat)
        with store.connection() as db:
            db.execute("update messages set status='running' where id=?", (rows[0]['id'],))
        with self.assertRaises(ValueError):
            store.set_summary(chat, 'partial', rows[1]['id'])
        with store.connection() as db:
            db.execute("update messages set turn_id=null,status='legacy' where id=?", (rows[1]['id'],))
        with self.assertRaises(ValueError):
            store.set_summary(chat, 'legacy', rows[1]['id'])
        self.assertIsNone(store.metadata(chat)['summary'])

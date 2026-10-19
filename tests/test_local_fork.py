from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from gemini_cli.client.local_chats import LocalChats


class LocalForkTests(unittest.TestCase):
    def store(self):
        store = LocalChats(Path('/unused'), temporary=True)
        self.addCleanup(store.close)
        return store

    def history(self, store, chat, count=15):
        rows = []
        for index in range(count):
            for ordinal, role in enumerate(('user', 'model', 'tool', 'model')):
                rows.append({'id': str(uuid4()), 'role': role, 'content': f'{index}:{ordinal}',
                    'turn_id': f'turn-{index}', 'request_id': f'request-{index}', 'event_index': ordinal,
                    'status': 'completed', 'name': 'read_file_lines' if ordinal in (1, 2) else None,
                    'call_id': f'call-{index}' if ordinal in (1, 2) else None,
                    'thought_signature': 'signature' if ordinal == 1 else None,
                    'args': {'path': 'safe', 'secret': 'hidden'} if ordinal == 1 else None,
                    'images': [{'data': 'private-image-bytes'}] if role == 'user' else []})
        store.append(chat, rows)
        return rows

    def test_long_prefix_signatures_redaction_summary_and_cancelled_tail(self):
        store = self.store()
        parent = store.create('source')['id']
        rows = self.history(store, parent)
        store.set_summary(parent, 'safe summary', rows[7]['id'])
        store.append(parent, [{'role': 'user', 'content': 'cancelled tail', 'turn_id': 'tail',
                               'status': 'cancelled'}])
        # Reapply privacy filtering even if an old database contains unfiltered tool text.
        with store.connection() as db:
            db.execute("update messages set content='private-tool-result' where id=?", (rows[2]['id'],))
        copied = store.fork(parent, 'copy')
        result = store.read(copied['id'])
        self.assertEqual(len(result), 60)
        self.assertEqual(copied['fork_parent_id'], parent)
        self.assertEqual(copied['fork_boundary'], rows[-1]['id'])
        self.assertEqual(copied['summary'], 'safe summary')
        self.assertEqual(copied['summary_boundary'], result[7]['id'])
        self.assertTrue(set(row['id'] for row in result).isdisjoint(row['id'] for row in rows))
        self.assertEqual((result[1]['call_id'], result[1]['thought_signature']), ('call-0', 'signature'))
        self.assertNotIn('private-tool-result', str(result))
        self.assertNotIn('private-image-bytes', str(result))
        self.assertNotIn('hidden', str(result))
        self.assertNotIn('cancelled tail', str(result))
        earlier = store.fork(parent, 'earlier', rows[3]['id'])
        self.assertEqual(len(store.read(earlier['id'])), 4)
        self.assertIsNone(earlier['summary'])
        self.assertIsNone(earlier['summary_boundary'])

    def test_wrong_profile_foreign_boundary_and_partial_turn_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = LocalChats(root)
            parent = store.create('source')['id']
            rows = self.history(store, parent, 2)
            other = store.create('other')['id']
            for chat, boundary in ((other, rows[-1]['id']), (parent, rows[0]['id']),
                                   (parent, rows[1]['id']), (parent, 'missing')):
                with self.subTest(boundary=boundary), self.assertRaises(ValueError):
                    store.fork(chat, 'unsafe', boundary)
            with self.assertRaises(LookupError):
                LocalChats(root, 'other-profile').fork(parent, 'foreign')
            with store.connection() as db:
                db.execute("update messages set status='running' where id=?", (rows[4]['id'],))
            latest = store.fork(parent, 'safe')
            self.assertEqual(len(store.read(latest['id'])), 4)
            with self.assertRaises(ValueError):
                store.fork(parent, 'unsafe', rows[-1]['id'])

    def test_failed_append_rolls_back_new_chat_and_all_copied_rows(self):
        store = self.store()
        parent = store.create('source')['id']
        self.history(store, parent, 1)
        before = store.list()
        append = store._append
        def fail_after_insert(db, chat_id, messages):
            append(db, chat_id, messages[:1])
            raise sqlite3.IntegrityError('forced failure')
        with patch.object(store, '_append', side_effect=fail_after_insert):
            with self.assertRaises(sqlite3.IntegrityError):
                store.fork(parent, 'incomplete')
        self.assertEqual(store.list(), before)
        with store.connection() as db:
            self.assertEqual(db.execute('select count(*) from messages').fetchone()[0], 4)

    def test_orphan_tool_batch_is_not_a_safe_boundary(self):
        store = self.store()
        chat = store.create('source')['id']
        rows = self.history(store, chat, 2)
        with store.connection() as db:
            db.execute("delete from messages where id=?", (rows[6]['id'],))
        with self.assertRaises(ValueError):
            store.fork(chat, 'orphan', rows[-1]['id'])
        self.assertEqual(len(store.read(store.fork(chat, 'safe')['id'])), 4)

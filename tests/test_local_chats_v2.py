from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from gemini_cli.client.local_chats import LocalChats


class LocalChatsV2Test(unittest.TestCase):
    def legacy_store(self, root):
        store = LocalChats(root)
        path = store.path
        store.close()
        path.unlink()
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript("""
                create table chats(id text primary key,title text not null,created_at text not null);
                create table messages(sequence integer primary key autoincrement,
                    chat_id text not null references chats(id) on delete cascade,
                    role text not null check(role in ('user','model','tool')),content text not null,
                    name text,args text,call_id text,thought_signature text);
                insert into chats values('chat','Original','2026-10-20');
                insert into messages values(7,'chat','user','task',null,null,null,null);
                insert into messages values(11,'chat','model','answer',null,null,'call','sig');
                pragma user_version=1;
            """)
        return path

    def test_legacy_reopen_preserves_rows_order_and_adds_stable_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = self.legacy_store(root)
            migrated = LocalChats(root)
            rows = migrated.read('chat')
            self.assertEqual([row['sequence'] for row in rows], [7, 11])
            self.assertEqual([row['event_index'] for row in rows], [7, 11])
            self.assertEqual([row['status'] for row in rows], ['legacy', 'legacy'])
            self.assertEqual([row['content'] for row in rows], ['task', 'answer'])
            self.assertEqual((rows[1]['call_id'], rows[1]['thought_signature']), ('call', 'sig'))
            for row in rows:
                UUID(row['id'])
                self.assertIsNone(row['request_id'])
                self.assertIsNone(row['turn_id'])
            self.assertEqual(LocalChats(root).read('chat'), rows)
            chat = migrated.list()[0]
            self.assertTrue(all(chat[key] is None for key in
                ('summary', 'summary_boundary', 'fork_parent_id', 'fork_boundary')))
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute('pragma user_version').fetchone()[0], 2)
                self.assertEqual(db.execute('select count(*) from generation_requests').fetchone()[0], 0)

    def test_future_version_refused_without_schema_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = self.legacy_store(root)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('pragma user_version=9')
                before = db.execute('select sql from sqlite_master order by name').fetchall()
            with self.assertRaises(ValueError):
                LocalChats(root)
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute('pragma user_version').fetchone()[0], 9)
                self.assertEqual(db.execute('select sql from sqlite_master order by name').fetchall(), before)

    def test_migration_failure_rolls_back_ddl_backfill_and_version(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = self.legacy_store(root)
            connect = sqlite3.connect
            def fail_index(*args, **kwargs):
                db = connect(*args, **kwargs)
                db.set_authorizer(lambda action, name, *_: sqlite3.SQLITE_DENY
                    if action == sqlite3.SQLITE_CREATE_INDEX and name == 'messages_event' else sqlite3.SQLITE_OK)
                return db
            with patch('gemini_cli.client.local_chats.sqlite3.connect', side_effect=fail_index):
                with self.assertRaises(sqlite3.DatabaseError):
                    LocalChats(root)
            with closing(connect(path)) as db, db:
                self.assertEqual(db.execute('pragma user_version').fetchone()[0], 1)
                self.assertNotIn('id', [row[1] for row in db.execute('pragma table_info(messages)')])
                self.assertEqual(db.execute('select sequence,content from messages').fetchall(),
                                 [(7, 'task'), (11, 'answer')])
            self.assertEqual(len(LocalChats(root).read('chat')), 2)

    def test_metadata_retries_conflicts_and_batch_rollback(self):
        store = LocalChats(Path('/unused'), temporary=True)
        self.addCleanup(store.close)
        chat = store.create('new')['id']
        event = {'role': 'user', 'content': 'task', 'id': str(uuid4()), 'turn_id': 'turn',
                 'request_id': 'request', 'event_index': 0, 'status': 'completed'}
        store.append(chat, [event])
        store.append(chat, [event])
        store.append(chat, [{key: value for key, value in event.items() if key != 'id'}])
        self.assertEqual(len(store.read(chat)), 1)
        self.assertTrue(event.items() <= store.read(chat)[0].items())
        for changed in ({'content': 'other'}, {'id': str(uuid4())}, {'status': 'failed'},
                        {'turn_id': 'other'}, {'event_index': 2}, {'status': 'unknown'}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                store.append(chat, [{'role': 'model', 'content': 'rolled back'}, event | changed])
        self.assertEqual(len(store.read(chat)), 1)
        other = store.create('other')['id']
        with self.assertRaises(ValueError):
            store.append(other, [event])
        self.assertEqual(store.read(other), [])
        with self.assertRaises(LookupError):
            store.append('missing', [])

    def test_metadata_keeps_existing_redaction_and_generated_uuid(self):
        store = LocalChats(Path('/unused'), temporary=True)
        self.addCleanup(store.close)
        chat = store.create('new')['id']
        store.append(chat, [{'role': 'tool', 'name': 'replace_in_file', 'content': 'secret',
                            'args': {'path': 'file', 'old': 'secret'}, 'status': 'cancelled'}])
        row = store.read(chat)[0]
        UUID(row['id'])
        self.assertNotIn('secret', str(row))
        self.assertEqual(row['args'], {'path': 'file'})
        self.assertEqual(row['status'], 'cancelled')

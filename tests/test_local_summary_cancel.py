"""Cancellation while SQLite waits for a writer must not commit a late summary."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch
from uuid import uuid4

from gemini_cli.client.local_chats import LocalChats


class LocalSummaryCancellationTests(unittest.TestCase):
    def prepare(self, directory):
        store = LocalChats(Path(directory))
        chat = store.create('summary')['id']
        rows = []
        for turn in range(3):
            for index, role in enumerate(('user', 'model')):
                rows.append({'id': str(uuid4()), 'turn_id': f'turn-{turn}',
                             'request_id': f'request-{turn}', 'event_index': index,
                             'role': role, 'content': role, 'status': 'completed'})
        store.append(chat, rows)
        store.set_summary(chat, 'original summary', rows[1]['id'])
        return store, chat, rows[1]['id'], rows[3]['id']

    def test_cancel_while_waiting_for_real_write_lock_preserves_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            store, chat, original_boundary, new_boundary = self.prepare(directory)
            cancelled, entered = Event(), Event()
            errors = []
            connection = store.connection
            @contextmanager
            def observed_connection():
                with connection() as db:
                    entered.set()
                    yield db
            def save():
                try:
                    store.set_summary(chat, 'late summary', new_boundary, cancelled=cancelled.is_set)
                except BaseException as error:
                    errors.append(error)
            locker = sqlite3.connect(store.path)
            worker = Thread(target=save)
            with patch.object(store, 'connection', observed_connection):
                try:
                    locker.execute('begin immediate')
                    worker.start()
                    self.assertTrue(entered.wait(2), 'summary worker did not reach SQLite')
                    self.assertTrue(worker.is_alive(), 'write lock did not hold worker')
                    cancelled.set()
                finally:
                    locker.rollback()
                    locker.close()
                    worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], InterruptedError)
            metadata = store.metadata(chat)
            self.assertEqual((metadata['summary'], metadata['summary_boundary']),
                             ('original summary', original_boundary))

    def test_cancel_during_summary_update_rolls_back_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            store, chat, original_boundary, new_boundary = self.prepare(directory)
            cancelled = Event()
            connection = store.connection
            @contextmanager
            def observed_connection():
                with connection() as db:
                    db.set_trace_callback(lambda sql: cancelled.set()
                        if sql.lower().startswith('update chats set summary=') else None)
                    yield db
            with patch.object(store, 'connection', observed_connection), self.assertRaises(InterruptedError):
                store.set_summary(chat, 'cancelled summary', new_boundary, cancelled=cancelled.is_set)
            metadata = store.metadata(chat)
            self.assertEqual((metadata['summary'], metadata['summary_boundary']),
                             ('original summary', original_boundary))


if __name__ == '__main__':
    unittest.main()

import importlib
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException


class FakeQuery:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = {}
        self.is_delete = False

    def select(self, *_args):
        return self

    def delete(self):
        self.is_delete = True
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def execute(self):
        self.db.queries.append((self.table, self.is_delete, self.filters.copy()))
        rows = self.db.chats if self.table == "chats" else self.db.messages
        matched = [row for row in rows if all(
            row.get(column) == value for column, value in self.filters.items()
        )]
        if self.is_delete:
            if self.db.fail_delete:
                raise RuntimeError("cascade failed")
            if self.db.delete_without_rows:
                return SimpleNamespace(data=[])
            self.db.chats = [row for row in self.db.chats if row not in matched]
            self.db.messages = [row for row in self.db.messages
                                if row["chat_id"] not in {chat["id"] for chat in matched}]
        return SimpleNamespace(data=matched)


class FakeDb:
    def __init__(self):
        self.chats = [
            {"id": "own", "user_id": "user-a"},
            {"id": "foreign", "user_id": "user-b"},
        ]
        self.messages = [
            {"chat_id": "own", "content": "own message"},
            {"chat_id": "foreign", "content": "foreign message"},
        ]
        self.queries = []
        self.fail_delete = False
        self.delete_without_rows = False

    def table(self, name):
        return FakeQuery(self, name)


class ChatDeletionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            "API_KEY": "test-key",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "test-anon-key",
        }):
            cls.server = importlib.import_module("server")

    def setUp(self):
        self.db = FakeDb()
        self.user = self.server.UserContext(user_id="user-a", db=self.db)

    def test_owned_chat_deletes_messages_by_cascade(self):
        result = self.server.delete_chat("own", self.user)
        self.assertEqual(result, {"status": "deleted"})
        self.assertEqual([chat["id"] for chat in self.db.chats], ["foreign"])
        self.assertEqual([message["chat_id"] for message in self.db.messages], ["foreign"])
        self.assertEqual(self.db.queries, [
            ("chats", False, {"id": "own", "user_id": "user-a"}),
            ("chats", True, {"id": "own", "user_id": "user-a"}),
        ])

    def test_foreign_and_missing_chat_do_not_delete(self):
        for chat_id in ("foreign", "missing"):
            with self.subTest(chat_id=chat_id):
                with self.assertRaises(HTTPException) as caught:
                    self.server.delete_chat(chat_id, self.user)
                self.assertEqual(caught.exception.status_code, 404)
                self.assertEqual(len(self.db.chats), 2)
                self.assertEqual(len(self.db.messages), 2)
        self.assertTrue(all(not is_delete for _, is_delete, _ in self.db.queries))

    def test_failed_cascade_does_not_report_deleted_or_change_data(self):
        self.db.fail_delete = True
        with self.assertRaises(HTTPException) as caught:
            self.server.delete_chat("own", self.user)
        self.assertEqual(caught.exception.status_code, 500)
        self.assertEqual(len(self.db.chats), 2)
        self.assertEqual(len(self.db.messages), 2)

    def test_zero_deleted_rows_does_not_report_deleted(self):
        self.db.delete_without_rows = True
        with self.assertRaises(HTTPException) as caught:
            self.server.delete_chat("own", self.user)
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(len(self.db.chats), 2)
        self.assertEqual(len(self.db.messages), 2)


if __name__ == "__main__":
    unittest.main()

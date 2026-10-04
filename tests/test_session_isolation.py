import importlib
import os
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch


class RlsTable:
    def __init__(self, db, name):
        self.db = db
        self.name = name
        self.filters = {}
        self.inserted = None

    def select(self, *_args):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def insert(self, row):
        self.inserted = row
        return self

    def execute(self):
        rows = self.db.rows[self.name]
        if self.inserted is not None:
            if self.name == "chats":
                if self.inserted["user_id"] != self.db.user_id:
                    raise PermissionError("RLS rejected chat insert")
                row = {"id": f"{self.db.user_id}-new", "created_at": "now", **self.inserted}
            else:
                if not self.db.owns_chat(self.inserted["chat_id"]):
                    raise PermissionError("RLS rejected message insert")
                row = self.inserted
            rows.append(row)
            return SimpleNamespace(data=[row])
        visible = [row for row in rows if (
            (self.name == "chats" and row["user_id"] == self.db.user_id)
            or (self.name == "messages" and self.db.owns_chat(row["chat_id"]))
        ) and all(row.get(key) == value for key, value in self.filters.items())]
        return SimpleNamespace(data=visible)


class RlsClient:
    def __init__(self, token, rows):
        self.user_id = token
        self.rows = rows
        self.auth = SimpleNamespace(get_user=lambda value: SimpleNamespace(
            user=SimpleNamespace(id=value) if value == token else None))

    def owns_chat(self, chat_id):
        return any(row["id"] == chat_id and row["user_id"] == self.user_id
                   for row in self.rows["chats"])

    def table(self, name):
        return RlsTable(self, name)


class SessionIsolationTest(unittest.TestCase):
    def test_parallel_users_keep_their_own_rls_context(self):
        with patch.dict(os.environ, {
            "API_KEY": "test-key",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "test-anon-key",
        }):
            sys.modules.pop("server", None)
            server = importlib.import_module("server")

        rows = {
            "chats": [
                {"id": "A-chat", "user_id": "A", "title": "A", "created_at": "now"},
                {"id": "B-chat", "user_id": "B", "title": "B", "created_at": "now"},
            ],
            "messages": [],
        }
        clients = []
        lock = threading.Lock()
        barrier = threading.Barrier(2)

        def factory(_url, _key, options=None):
            token = options.headers["Authorization"].removeprefix("Bearer ")
            db = RlsClient(token, rows)
            with lock:
                clients.append(db)
            return db

        def request(user_id):
            context = server.get_current_user(f"Bearer {user_id}")
            barrier.wait()
            chats = server.get_chats(context)
            created = server.create_chat(server.ChatCreate(title="new"), context)
            server.save_message_to_db(context.db, created.id, "user", user_id)
            own_messages = context.db.table("messages").select("*").execute().data
            return context, chats, created, own_messages

        with patch.object(server, "create_client", side_effect=factory):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(request, ("A", "B")))

        self.assertIsNot(clients[0], clients[1])
        for user_id, (context, chats, created, messages) in zip(("A", "B"), results):
            self.assertEqual(context.user_id, user_id)
            self.assertEqual({chat.id for chat in chats}, {f"{user_id}-chat"})
            self.assertEqual(created.id, f"{user_id}-new")
            self.assertEqual([row["content"] for row in messages], [user_id])


if __name__ == "__main__":
    unittest.main()

import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from dotenv import load_dotenv
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError
from supabase import create_client
from supabase.lib.client_options import SyncClientOptions


class SupabaseIsolationTest(unittest.TestCase):
    def test_two_users_with_real_rls(self):
        if os.getenv("RUN_SUPABASE_INTEGRATION") != "1":
            self.skipTest("Set RUN_SUPABASE_INTEGRATION=1 to run against Supabase")
        load_dotenv()
        names = (
            "SUPABASE_URL", "SUPABASE_ANON_KEY",
            "TEST_USER_A_EMAIL", "TEST_USER_A_PASSWORD",
            "TEST_USER_B_EMAIL", "TEST_USER_B_PASSWORD",
        )
        if any(not os.getenv(name) for name in names):
            self.skipTest("Real Supabase test credentials are not configured")

        from server import app

        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_ANON_KEY"]
        users = []
        for letter in ("A", "B"):
            auth = create_client(url, key).auth.sign_in_with_password({
                "email": os.environ[f"TEST_USER_{letter}_EMAIL"],
                "password": os.environ[f"TEST_USER_{letter}_PASSWORD"],
            })
            self.assertIsNotNone(auth.session)
            token = auth.session.access_token
            db = create_client(url, key, options=SyncClientOptions(
                headers={"Authorization": f"Bearer {token}"}))
            users.append((auth.user.id, token, db))

        self.assertNotEqual(users[0][0], users[1][0])
        barrier = threading.Barrier(2)
        run_id = uuid4().hex[:12]
        chat_ids = {}
        chat_lock = threading.Lock()

        def request(letter, token):
            with TestClient(app) as http:
                barrier.wait()
                created = http.post("/chats", json={"title": f"rls-test-{run_id}-{letter}"},
                                    headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(created.status_code, 200, created.text)
                chat_id = created.json()["id"]
                with chat_lock:
                    chat_ids[0 if letter == "A" else 1] = chat_id
                listed = http.get("/chats", headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(listed.status_code, 200, listed.text)
                return listed.json()

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(request, ("A", "B"),
                                        (users[0][1], users[1][1])))

            for index, (user_id, _token, db) in enumerate(users):
                own_chat = chat_ids[index]
                other_chat = chat_ids[1 - index]
                self.assertIn(own_chat, {row["id"] for row in results[index]})
                self.assertNotIn(other_chat, {row["id"] for row in results[index]})
                self.assertEqual(db.table("chats").select("id")
                                 .eq("id", other_chat).execute().data, [])
                with self.assertRaises(APIError):
                    db.table("chats").insert({
                        "user_id": users[1 - index][0], "title": "forbidden",
                    }).execute()

                db.table("messages").insert({
                    "chat_id": own_chat, "role": "user",
                    "content": f"rls-test-{run_id}-{user_id}",
                }).execute()
                self.assertEqual(db.table("messages").select("content")
                                 .eq("chat_id", other_chat).execute().data, [])
                with self.assertRaises(APIError):
                    db.table("messages").insert({
                        "chat_id": other_chat, "role": "user",
                        "content": "forbidden",
                    }).execute()
        finally:
            for index, (_user_id, _token, db) in enumerate(users):
                if index in chat_ids:
                    db.table("messages").delete().eq("chat_id", chat_ids[index]).execute()
                    db.table("chats").delete().eq("id", chat_ids[index]).execute()


if __name__ == "__main__":
    unittest.main()

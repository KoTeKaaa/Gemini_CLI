"""Opt-in real auth/RLS/routes; Gemini generation requires a second explicit gate."""
import json
import os
import subprocess
import sys
import unittest
from uuid import uuid4


@unittest.skipUnless(os.getenv('RUN_SUPABASE_INTEGRATION') == '1', 'Real Supabase gate is disabled')
class HistoryIntegrationTests(unittest.TestCase):
    def safe(self, operation):
        try:
            return operation()
        except Exception as error:
            raise AssertionError(f'Integration operation failed ({type(error).__name__})') from None

    def setUp(self):
        from dotenv import load_dotenv
        load_dotenv()
        required = ('SUPABASE_URL', 'SUPABASE_ANON_KEY', 'TEST_USER_A_EMAIL',
                    'TEST_USER_A_PASSWORD', 'TEST_USER_B_EMAIL', 'TEST_USER_B_PASSWORD')
        if any(not os.getenv(name) for name in required):
            self.skipTest('Real integration credentials are not configured')
        from supabase import create_client
        from supabase.lib.client_options import SyncClientOptions
        from fastapi.testclient import TestClient
        from gemini_cli.server.history_store import HistoryStore
        from server import app
        self.app, self.http_type, self.store_type = app, TestClient, HistoryStore
        self.users, self.created = [], []
        self.addCleanup(self.cleanup_chats)
        for letter in ('A', 'B'):
            auth = self.safe(lambda: create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_ANON_KEY'])
                .auth.sign_in_with_password({'email': os.environ[f'TEST_USER_{letter}_EMAIL'],
                                            'password': os.environ[f'TEST_USER_{letter}_PASSWORD']}))
            self.assertIsNotNone(auth.session, 'Test account login must succeed')
            token = auth.session.access_token
            db = self.safe(lambda: create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_ANON_KEY'],
                options=SyncClientOptions(headers={'Authorization': f'Bearer {token}'})))
            self.users.append((auth.user.id, {'Authorization': f'Bearer {token}'}, db))
        self.assertNotEqual(self.users[0][0], self.users[1][0])

    def cleanup_chats(self):
        for owner, chat in reversed(self.created):
            user_id, _, db = self.users[owner]
            self.safe(lambda: db.table('chats').delete().eq('id', chat).eq('user_id', user_id).execute())

    def create_chat(self, http, owner=0):
        response = http.post('/chats', headers=self.users[owner][1], json={'title': 's4-integration-' + uuid4().hex})
        self.assertEqual(response.status_code, 200, 'Create test-owned chat')
        chat = response.json()['id']
        self.created.append((owner, chat))
        return chat

    def seed(self, chat, owner=0):
        user_id, _, db = self.users[owner]
        store = self.store_type(db, user_id)
        for index in range(5):
            request, turn, call = str(uuid4()), str(uuid4()), str(uuid4())
            rows = [{'role': 'user', 'content': f'Integration task {index}'},
                    {'role': 'model', 'name': 'read_file_lines', 'content': 'call',
                     'args': {'path': 'test.txt', 'secret': 'PRIVATE_ARGUMENT'},
                     'call_id': call, 'thought_signature': 'c2ln'},
                    {'role': 'tool', 'name': 'read_file_lines', 'content': 'PRIVATE_TOOL_OUTPUT', 'call_id': call},
                    {'role': 'model', 'content': f'Completed task {index}'}]
            self.safe(lambda: store.append(chat, rows, turn_id=turn, request_id=request, status='completed'))
            self.safe(lambda: store.append(chat, rows, turn_id=turn, request_id=request, status='completed'))
        saved = self.safe(lambda: store.read(chat))
        self.assertEqual(len(saved), 20, 'Identical event retries must not duplicate rows')
        self.assertNotIn('PRIVATE_ARGUMENT', json.dumps(saved))
        self.assertNotIn('PRIVATE_TOOL_OUTPUT', json.dumps(saved))
        return store, saved

    def test_auth_history_context_summary_fork_and_reopen(self):
        with self.http_type(self.app) as http:
            chat = self.create_chat(http)
            store, rows = self.seed(chat)
            self.create_chat(http, owner=1)
            path, headers = f'/chats/{chat}/history', self.users[0][1]
            self.assertEqual(http.get(path).status_code, 401)
            self.assertEqual(http.get(path, headers=self.users[1][1]).status_code, 404)
            history = http.get(path, headers=headers)
            self.assertEqual(history.status_code, 200)
            self.assertEqual(len(history.json()), 20)
            context = http.post('/chat/context', headers=headers, json={
                'chat_id': chat, 'message': 'Next task', 'supported_tools': []})
            self.assertEqual(context.status_code, 200, 'Actual context metadata endpoint')
            self.assertIn('input_token_limit', context.json())
            self.assertIsInstance(context.json()['input_tokens'], int)
            boundary = rows[7]['id']
            summary = {'chat_id': chat, 'summary': 'Two completed integration tasks.', 'boundary_id': boundary}
            self.assertEqual(http.post('/chat/summary', headers=self.users[1][1], json=summary).status_code, 404)
            self.assertEqual(http.post('/chat/summary', headers=headers, json=summary).status_code, 200)
            self.assertEqual(self.safe(lambda: store.metadata(chat))['summary_boundary'], boundary)
            fork = http.post(f'/chats/{chat}/fork', headers=headers, json={'title': 's4-integration-fork'})
            self.assertEqual(fork.status_code, 200)
            child = fork.json()
            self.created.append((0, child['id']))
            copied = self.safe(lambda: store.read(child['id']))
            self.assertEqual(len(copied), 20)
            self.assertEqual(child['fork_parent_id'], chat)
            self.assertEqual(child['fork_boundary'], rows[-1]['id'])
            self.assertEqual(child['summary_boundary'], copied[7]['id'])
            self.assertTrue({row['id'] for row in copied}.isdisjoint(row['id'] for row in rows))
            self.assertEqual(copied[1]['thought_signature'], rows[1]['thought_signature'])
            self.assertEqual(copied[1]['call_id'], copied[2]['call_id'])
            self.assertNotIn('PRIVATE_', json.dumps(copied))
        # A new interpreter imports a new server instance against the durable DB.
        code = """
import json, os
from fastapi.testclient import TestClient
from server import app
with TestClient(app) as http:
    response = http.get(os.environ['S4_REOPEN_PATH'],
                        headers={'Authorization': os.environ['S4_REOPEN_AUTH']})
    assert response.status_code == 200
    assert [row['id'] for row in response.json()] == json.loads(os.environ['S4_REOPEN_IDS'])
"""
        reopened = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True,
            timeout=45, env={**os.environ, 'S4_REOPEN_PATH': path,
                            'S4_REOPEN_AUTH': headers['Authorization'],
                            'S4_REOPEN_IDS': json.dumps([row['id'] for row in rows])})
        self.assertEqual(reopened.returncode, 0, 'A fresh server process must restore the exact event order')

    @unittest.skipUnless(os.getenv('RUN_GEMINI_INTEGRATION') == '1', 'Real Gemini generation gate is disabled')
    def test_real_compaction_stream_and_duplicate_reservation(self):
        from gemini_cli.protocol.models import MODEL_IDS
        with self.http_type(self.app) as http:
            chat = self.create_chat(http)
            store, _ = self.seed(chat)
            headers = self.users[0][1]
            candidate = http.post('/chat/compact', headers=headers, json={
                'chat_id': chat, 'model_name': MODEL_IDS[0], 'request_id': str(uuid4())})
            self.assertEqual(candidate.status_code, 200, 'Real compact generation')
            result = candidate.json()
            self.assertEqual(result['reason'], 'ready', 'Real provider must return a usable summary')
            self.assertIsNone(self.safe(lambda: store.metadata(chat))['summary'])
            applied = http.post('/chat/summary', headers=headers, json={
                'chat_id': chat, 'summary': result['summary'], 'boundary_id': result['boundary_id']})
            self.assertEqual(applied.status_code, 200)
            fresh = self.create_chat(http)
            request = {'chat_id': fresh, 'model_name': MODEL_IDS[0], 'message': 'Ответь одним словом: готово.',
                       'supported_tools': [], 'turn_id': str(uuid4()), 'request_id': str(uuid4())}
            response = http.post('/chat/stream', headers=headers, json=request)
            self.assertEqual(response.status_code, 200, 'Real Gemini stream')
            events = [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith('data:')]
            self.assertFalse(any(row['type'] == 'error' for row in events), 'Real stream must complete without errors')
            self.assertTrue(any(row['type'] == 'text' and row['content'].strip() for row in events))
            before = self.safe(lambda: store.read(fresh))
            duplicate = http.post('/chat/stream', headers=headers, json=request)
            if duplicate.status_code != 409:
                self.assertEqual(duplicate.status_code, 200)
                errors = [json.loads(line[5:].strip()) for line in duplicate.text.splitlines() if line.startswith('data:')]
                self.assertTrue(any(row['type'] == 'error' and 'уже учтён' in row.get('content', '') for row in errors))
                self.assertFalse(any(row['type'] == 'text' for row in errors))
            self.assertEqual(self.safe(lambda: store.read(fresh)), before, 'Duplicate must not modify durable history')

from types import SimpleNamespace
from uuid import UUID, uuid4
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from gemini_cli.server.history_routes import register_history_routes


class Row(BaseModel):
    role: str
    content: str
    id: str | None = None
    turn_id: str | None = None
    status: str | None = None


class Payload(BaseModel):
    chat_id: str | None = None
    message: str = ''
    model_name: str = 'gemini-3.5-flash-lite'
    history: list[Row] = Field(default_factory=list, max_length=1000)
    images: list = []
    turn_id: UUID | None = None
    summary: str | None = None
    summary_boundary: UUID | None = None
    continue_after_tool: bool = False
    supported_tools: list[str] | None = None


class HistoryRoutesTests(unittest.TestCase):
    def setUp(self):
        self.chat = str(uuid4())
        self.store = Mock()
        self.store.read.return_value = [{'role': 'user', 'content': 'saved'},
                                        {'role': 'model', 'content': 'answer'}]
        self.store.metadata.return_value = {}
        def scoped(db, user_id):
            if user_id != 'owner':
                raise LookupError('foreign')
            return self.store
        self.patch = patch('gemini_cli.server.history_routes.HistoryStore', side_effect=scoped)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        def user(authorization: str | None = Header(None)):
            if authorization is None:
                raise HTTPException(401, 'missing')
            return SimpleNamespace(db=object(), user_id=authorization)
        self.provider = Mock()
        self.provider.models.get.return_value = SimpleNamespace(input_token_limit=10000, output_token_limit=1000)
        self.get_provider = Mock(return_value=self.provider)
        self.authorize = Mock(return_value={'features': ['execute_command']})
        self.reserve = Mock()
        app = FastAPI()
        register_history_routes(app, get_user=user, provider=self.get_provider, payload_model=Payload,
                                authorize=self.authorize, reserve=self.reserve)
        self.client = TestClient(app)
        self.headers = {'Authorization': 'owner'}

    def test_history_requires_auth_and_owner_and_fork_uses_scoped_rpc(self):
        url = f'/chats/{self.chat}/history'
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get(url, headers={'Authorization': 'foreign'}).status_code, 404)
        self.assertEqual(self.client.get(url, headers=self.headers).json(), self.store.read.return_value)
        self.store.fork.return_value = {'id': str(uuid4())}
        response = self.client.post(f'/chats/{self.chat}/fork', json={'title': 'copy'}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.store.fork.assert_called_once_with(self.chat, 'copy', None)
        self.assertEqual(self.client.get('/chats/not-uuid/history', headers=self.headers).status_code, 422)

    def test_context_uses_owned_history_and_subscription_before_metadata(self):
        with patch('gemini_cli.server.history_routes.to_gemini', side_effect=lambda rows: rows) as convert:
            response = self.client.post('/chat/context', json={'chat_id': self.chat, 'message': 'next',
                'supported_tools': ['execute_command']}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(convert.call_args.args[0]), 3)
        self.assertEqual(response.json()['input_token_limit'], 10000)
        self.assertIsInstance(response.json()['input_tokens'], int)
        self.provider.models.generate_content_stream.assert_not_called()
        self.authorize.side_effect = HTTPException(403, 'inactive')
        self.get_provider.reset_mock()
        response = self.client.post('/chat/context', json={}, headers=self.headers)
        self.assertEqual(response.status_code, 403)
        self.get_provider.assert_not_called()


    def completed_history(self):
        rows = []
        for index in range(5):
            turn = str(uuid4())
            rows += [{'role': 'user', 'content': str(index), 'id': str(uuid4()),
                      'turn_id': turn, 'status': 'completed'},
                     {'role': 'model', 'content': 'answer', 'id': str(uuid4()),
                      'turn_id': turn, 'status': 'completed'}]
        return rows

    def test_compact_candidate_is_budgeted_but_never_persisted(self):
        self.store.read.return_value = self.completed_history()
        with patch('gemini_cli.server.history_routes.stream_events', return_value=iter([
                {'type': 'text', 'content': 'safe summary'}])):
            response = self.client.post('/chat/compact', json={'chat_id': self.chat,
                'request_id': str(uuid4())}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['reason'], 'ready')
        self.reserve.assert_called_once()
        self.store.set_summary.assert_not_called()
        self.reserve.side_effect = HTTPException(429, 'exhausted')
        response = self.client.post('/chat/compact', json={'chat_id': self.chat,
            'request_id': str(uuid4())}, headers=self.headers)
        self.assertEqual(response.status_code, 429)

    def test_compact_without_boundary_has_no_provider_cost(self):
        response = self.client.post('/chat/compact', json={'chat_id': self.chat,
            'request_id': str(uuid4())}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['reason'], 'no_completed_boundary')
        self.reserve.assert_not_called()
        self.get_provider.assert_not_called()

    def test_summary_apply_validates_owner_and_whole_boundary(self):
        self.store.read.return_value = rows = self.completed_history()
        payload = {'chat_id': self.chat, 'summary': 'safe', 'boundary_id': rows[3]['id']}
        response = self.client.post('/chat/summary', json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.store.set_summary.assert_called_once_with(self.chat, 'safe', rows[3]['id'])
        self.store.set_summary.reset_mock()
        response = self.client.post('/chat/summary', json=dict(payload, boundary_id=rows[-1]['id']), headers=self.headers)
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/chat/summary', json=payload, headers={'Authorization': 'foreign'})
        self.assertEqual(response.status_code, 404)
        self.store.set_summary.assert_not_called()

    def test_temp_compaction_accepts_over_stream_row_limit(self):
        rows = self.completed_history() * 101
        with patch('gemini_cli.server.history_routes.stream_events', return_value=iter([
                {'type': 'text', 'content': 'summary'}])):
            response = self.client.post('/chat/compact', json={'history': rows,
                'request_id': str(uuid4())}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['reason'], 'ready')


class RemoteHistoryAPITests(unittest.TestCase):
    def test_remote_history_context_fork_requests_are_authenticated_and_closed(self):
        from gemini_cli.backends.remote import RemoteBackend
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            transport = Mock()
            response = Mock(status_code=200)
            response.json.return_value = {'result': 'ok'}
            transport.get.return_value = transport.post.return_value = response
            backend = RemoteBackend('https://example.test', transport=transport, profile_root=Path(directory))
            backend.token = 'private-token'
            chat = str(uuid4())
            self.assertEqual(backend.get_history(chat), {'result': 'ok'})
            backend.context_info({'chat_id': chat})
            backend.fork_chat(chat, 'copy')
            self.assertEqual(transport.get.call_args.kwargs['headers'], {'Authorization': 'Bearer private-token'})
            self.assertFalse(transport.post.call_args.kwargs['allow_redirects'])
            self.assertEqual(response.close.call_count, 3)
            response.status_code = 404
            with self.assertRaises(LookupError):
                backend.get_history(chat)
            self.assertEqual(response.close.call_count, 4)

    def test_remote_compact_cancelled_candidate_is_not_applied(self):
        from gemini_cli.backends.remote import RemoteBackend
        from threading import Event
        backend = RemoteBackend('https://example.test')
        cancelled = Event()
        def candidate(path, payload=None):
            self.assertEqual(path, '/chat/compact')
            cancelled.set()
            return {'summary': 'late', 'boundary_id': str(uuid4()), 'reason': 'ready'}
        backend._history_request = Mock(side_effect=candidate)
        result = backend.compact_chat({'chat_id': str(uuid4())}, cancelled.is_set)
        self.assertEqual(result['reason'], 'cancelled')
        self.assertIsNone(result['summary'])
        self.assertEqual(backend._history_request.call_count, 1)

    def test_remote_compact_applies_only_ready_saved_candidate(self):
        from gemini_cli.backends.remote import RemoteBackend
        backend = RemoteBackend('https://example.test')
        candidate = {'summary': 'safe', 'boundary_id': str(uuid4()), 'reason': 'ready'}
        backend._history_request = Mock(side_effect=[candidate, {'status': 'ok'}])
        chat = str(uuid4())
        self.assertEqual(backend.compact_chat({'chat_id': chat}), candidate)
        self.assertEqual(backend._history_request.call_args_list[1].args,
                         ('/chat/summary', {'chat_id': chat, 'summary': 'safe',
                                            'boundary_id': candidate['boundary_id']}))

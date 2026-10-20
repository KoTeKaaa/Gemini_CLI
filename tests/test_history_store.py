import unittest
from unittest.mock import Mock
from uuid import uuid4
from gemini_cli.server.history_store import HistoryStore


class HistoryStoreTests(unittest.TestCase):
    def test_private_results_and_signatures_are_stored_without_losing_identity(self):
        db = Mock()
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"id": "chat"}]
        store = HistoryStore(db, "owner")
        request, turn = str(uuid4()), str(uuid4())
        rows = [{"role": "model", "name": "read_local_files", "content": "call",
                 "call_id": "tool", "thought_signature": "cw=="},
                {"role": "tool", "name": "read_local_files", "content": "PRIVATE", "call_id": "tool"}]
        self.assertEqual(store.append("chat", rows, turn_id=turn, request_id=request), 2)
        events = db.rpc.call_args.args[1]["events"]
        self.assertEqual(events[0]["thought_signature"], "cw==")
        self.assertEqual(events[1]["event_index"], 1)
        self.assertNotIn("PRIVATE", str(events))
        first_id = events[0]["id"]
        store.append("chat", rows, turn_id=turn, request_id=request)
        self.assertEqual(db.rpc.call_args.args[1]["events"][0]["id"], first_id)

    def test_foreign_chat_is_rejected_before_rpc(self):
        db = Mock()
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        with self.assertRaises(LookupError):
            HistoryStore(db, "owner").append("foreign", [{"role": "user", "content": "x"}])
        db.rpc.assert_not_called()

    def test_read_paginates_past_supabase_default_row_limit(self):
        from tests.test_chat_stream_ownership import FakeDb
        db = FakeDb()
        db.messages = [{"chat_id": "own", "sequence": i, "content": str(i)} for i in range(1237)]
        rows = HistoryStore(db, "user-a").read("own")
        self.assertEqual(len(rows), 1237)
        self.assertEqual(rows[-1]["sequence"], 1236)

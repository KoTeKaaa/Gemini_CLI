from pathlib import Path
import tempfile
import unittest

from gemini_cli.tools.local.changes import ChangeHistory
from gemini_cli.tools.local.checkpoints import CheckpointStore
from gemini_cli.tools.local.undo import undo


class ChangeHistoryTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        self.root = base / "workspace"
        self.root.mkdir()
        self.file = self.root / "file.py"
        self.file.write_bytes(b"original\n")
        self.history = ChangeHistory(str(self.root), store=CheckpointStore(base / "private"))

    def write(self, turn, text):
        journal = self.history.begin_turn(turn)
        item = journal.propose("file.py", text)
        journal.write(item)
        self.history.trim()
        return item

    def test_multiple_turns_aggregate_and_plain_turn_preserves_changes(self):
        self.write("first", "intermediate\n")
        self.write("second", "final\n")
        self.history.begin_turn("no edits")
        self.history.trim()
        diff = self.history.file_diff(self.history.resolve_path("file.py"))
        self.assertIn("-original", diff)
        self.assertIn("+final", diff)
        self.assertNotIn("intermediate", diff)
        self.assertIn("ходов: 2", self.history.listing())

    def test_undo_disappears_then_new_write_starts_new_baseline(self):
        item = self.write("first", "agent\n")
        undo(self.history, selected_paths=[item.before.path], approve=lambda: True)
        self.assertEqual(item.diff(), "")
        self.assertEqual(self.history.active_files(), {})
        self.assertNotIn("file.py", self.history.listing())
        self.write("second", "new agent\n")
        diff = self.history.file_diff(self.history.resolve_path("file.py"))
        self.assertIn("-original", diff)
        self.assertNotIn("+agent\n", diff)

    def test_manual_gap_has_separate_diff_and_blocks_undo(self):
        self.write("first", "first agent\n")
        self.file.write_text("manual\n")
        self.write("second", "second agent\n")
        diff = self.history.file_diff(self.history.resolve_path("file.py"))
        self.assertIn("-manual", diff)
        self.assertIn("отдельная цепочка", diff)
        result = undo(self.history, selected_paths=[self.history.resolve_path("file.py")], approve=lambda: True)
        self.assertIn("Конфликт", result[0]["status"])
        self.assertEqual(self.file.read_text(), "second agent\n")

    def test_scope_and_retention(self):
        self.write("first", "agent\n")
        other = ChangeHistory(str(self.root), store=self.history.store)
        self.assertEqual(other.active_files(), {})
        for i in range(33):
            self.write(str(i), f"agent {i}\n")
        self.assertEqual(len(self.history.turns), 32)
        self.assertEqual(len({e.turn_id for e in self.history.entries}), 32)

    def test_net_zero_chain_is_not_listed(self):
        self.write("first", "agent\n")
        self.write("second", "original\n")
        self.assertEqual(self.history.active_files(), {})
        self.assertEqual(self.history.turns, [])
        self.write("third", "new change\n")
        self.assertIn("ходов: 1", self.history.listing())

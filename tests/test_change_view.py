import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from gemini_cli.client.change_view import change_pages, diff_application, select_changes, select_undo_files
from gemini_cli.tools.local.changes import ChangeSet


class ChangeViewTest(unittest.TestCase):
    def test_zero_selection_and_final_refusal_do_not_apply(self):
        with tempfile.TemporaryDirectory() as root:
            changes = ChangeSet(root)
            item = changes.propose("one", "new")
            for selected in ([], [(0, 0)]):
                item.status = "proposed"
                with patch("gemini_cli.client.change_view.diff_application", return_value=Mock()), \
                     patch("gemini_cli.client.change_view.checkboxlist_dialog", return_value=Mock(run=lambda: selected)), \
                     patch("gemini_cli.client.change_view.radiolist_dialog", return_value=Mock(run=lambda: "cancel")):
                    select_changes(changes, [item])
                self.assertEqual(item.status, "skipped")
                self.assertFalse(Path(root, "one").exists())

    def test_write_without_opening_diff(self):
        with tempfile.TemporaryDirectory() as root:
            changes = ChangeSet(root)
            item = changes.propose("one", "new")
            with patch("gemini_cli.client.change_view.diff_application") as preview, \
                 patch("gemini_cli.client.change_view.checkboxlist_dialog", return_value=Mock(run=lambda: [(0, 0)])), \
                 patch("gemini_cli.client.change_view.radiolist_dialog", return_value=Mock(run=lambda: "write")):
                select_changes(changes, [item])
            preview.assert_not_called()
            self.assertEqual(item.status, "proposed")
            self.assertEqual(item.target, b"new")

    def test_explicit_diff_returns_to_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            changes = ChangeSet(root)
            item = changes.propose("empty", "")
            actions = iter(["diff", "write"])
            with patch("gemini_cli.client.change_view.diff_application", return_value=Mock()) as preview, \
                 patch("gemini_cli.client.change_view.checkboxlist_dialog", return_value=Mock(run=lambda: [(0, -1)])), \
                 patch("gemini_cli.client.change_view.radiolist_dialog", side_effect=lambda **kw: Mock(run=lambda: next(actions))):
                select_changes(changes, [item])
            preview.assert_called_once()
            self.assertIn("Создание пустого файла", preview.call_args.args[0][0][1])
            self.assertEqual(item.status, "proposed")

    def test_change_selection_preserves_previous_selection(self):
        with tempfile.TemporaryDirectory() as root:
            changes = ChangeSet(root)
            items = [changes.propose(name, "new") for name in ("one", "two")]
            selections = iter([[(0, 0)], [(1, 0)]])
            actions = iter(["select", "write"])
            with patch("gemini_cli.client.change_view.checkboxlist_dialog",
                       side_effect=lambda **kw: Mock(run=lambda: next(selections))) as choose, \
                 patch("gemini_cli.client.change_view.radiolist_dialog", side_effect=lambda **kw: Mock(run=lambda: next(actions))):
                select_changes(changes, items)
            self.assertEqual(choose.call_args.kwargs["default_values"], {(0, 0)})
            self.assertEqual([item.status for item in items], ["skipped", "proposed"])

    def test_undo_selects_unique_applied_files(self):
        from prompt_toolkit.widgets import CheckboxList
        with tempfile.TemporaryDirectory() as root:
            changes = ChangeSet(root)
            one = changes.propose("one", "new")
            two = changes.propose("two", "new")
            changes.propose("skipped", "new")
            one.status = two.status = "applied"
            changes.entries.append(one)
            for selected, expected in ((None, []), ([], []),
                                       ([one.before.path], [one.before.path]),
                                       ([one.before.path, two.before.path], [one.before.path, two.before.path])):
                with self.subTest(selected=selected), \
                     patch("gemini_cli.client.change_view.Application", return_value=Mock(run=lambda: selected)), \
                     patch("gemini_cli.client.change_view.CheckboxList", wraps=CheckboxList) as choose:
                    self.assertEqual(select_undo_files(changes), expected)
                self.assertEqual(choose.call_args.kwargs["default_values"], [])
                self.assertEqual(len(choose.call_args.kwargs["values"]), 2)
            with patch("gemini_cli.client.change_view.Application") as choose:
                self.assertEqual(select_undo_files(changes, interactive=False), [])
                self.assertEqual(select_undo_files(ChangeSet(root)), [])
                choose.assert_not_called()

    def test_undo_keyboard_selection_all_and_escape(self):
        from prompt_toolkit.application import Application
        with tempfile.TemporaryDirectory() as root:
            changes = ChangeSet(root)
            one, two = [changes.propose(name, "new") for name in ("one", "two")]
            one.status = two.status = "applied"
            for keys, expected in ((" \t\r", [one.before.path]),
                                   ("\t\t\r", [one.before.path, two.before.path]),
                                   ("\x1b", [])):
                with self.subTest(keys=keys), create_pipe_input() as pipe:
                    pipe.send_text(keys)
                    with patch("gemini_cli.client.change_view.Application",
                               side_effect=lambda **kw: Application(**kw, input=pipe, output=DummyOutput())):
                        self.assertEqual(select_undo_files(changes), expected)

    def test_empty_proposal_actual_and_long_unicode_lines(self):
        with tempfile.TemporaryDirectory() as root:
            changes = ChangeSet(root)
            self.assertEqual(change_pages(changes), [])
            item = changes.propose("one", "длинная" * 10000)
            self.assertEqual(change_pages(changes), [])
            self.assertIn("предложено", change_pages(changes, proposed=True)[0][0])
            Path(root, "one").write_bytes(item.proposed)
            changes.applied(item)
            self.assertIn("фактически записано", change_pages(changes)[0][0])

    def test_navigation_search_and_exit(self):
        async def run():
            with create_pipe_input() as pipe:
                app = diff_application([("one", "-old\n+new\n"), ("two", "another\n")],
                                       input=pipe, output=DummyOutput())
                async def type_keys():
                    await asyncio.sleep(.05)
                    pipe.send_text("n")
                    await asyncio.sleep(.05)
                    pipe.send_text("/another\r")
                    await asyncio.sleep(.05)
                    pipe.send_text("q")
                task = asyncio.create_task(type_keys())
                await asyncio.wait_for(app.run_async(), 3)
                await task
                self.assertTrue(app.full_screen)
        asyncio.run(run())

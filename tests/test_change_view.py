import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from gemini_cli.client.change_view import change_pages, diff_application, select_changes
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
                     patch("gemini_cli.client.change_view.yes_no_dialog", return_value=Mock(run=lambda: False)):
                    select_changes(changes, [item])
                self.assertEqual(item.status, "skipped")
                self.assertFalse(Path(root, "one").exists())

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

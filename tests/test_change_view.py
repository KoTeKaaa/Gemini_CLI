import asyncio
import unittest
from unittest.mock import Mock, patch

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from gemini_cli.client.change_view import change_pages, diff_application, handle_change_command


class ChangeViewTest(unittest.TestCase):
    def journal(self):
        changes = Mock(root="/workspace")
        changes.active_files.return_value = {"/workspace/one name.py": [], "/workspace/proposed": []}
        changes.resolve_path.side_effect = lambda path: "/workspace/" + path
        changes.file_diff.side_effect = lambda path: "DIFF " + path
        changes.listing.return_value = "#1 — one name.py\n#2 — proposed"
        return changes

    def test_bare_commands_list_files_without_diff_or_undo(self):
        changes = self.journal()
        for command in ("/diff", "/undo"):
            with self.subTest(command=command), \
                 patch("gemini_cli.client.change_view.diff_application") as view, \
                 patch("gemini_cli.client.change_view.undo") as restore:
                console = Mock(is_terminal=True)
                self.assertTrue(handle_change_command(command, changes, console))
                self.assertIn("#1 — one name.py", str(console.print.call_args.args[0].renderable))
                view.assert_not_called()
                restore.assert_not_called()

    def test_explicit_diff_opens_only_requested_path_and_accepts_spaces(self):
        changes = self.journal()
        for path in ("one name.py", "proposed"):
            with self.subTest(path=path), patch("gemini_cli.client.change_view.diff_application", return_value=Mock()) as view:
                self.assertTrue(handle_change_command("/diff " + path, changes, Mock(is_terminal=True)))
                changes.resolve_path.assert_called_with(path)
                self.assertEqual(view.call_args.args[0], [(path, "DIFF /workspace/" + path)])
                view.return_value.run.assert_called_once()

    def test_explicit_undo_is_direct_and_scoped(self):
        changes = self.journal()
        with patch("gemini_cli.client.change_view.undo", return_value=[
            {"filepath": "/workspace/one name.py", "status": "Восстановлено"}]) as restore, \
             patch("gemini_cli.client.change_view.diff_application") as view:
            console = Mock(is_terminal=True)
            self.assertTrue(handle_change_command("/undo one name.py", changes, console))
            self.assertEqual(restore.call_args.kwargs["selected_paths"], ["/workspace/one name.py"])
            self.assertTrue(restore.call_args.kwargs["approve"]())
            self.assertIn("Восстановлено", str(console.print.call_args.args[0].renderable))
            view.assert_not_called()

    def test_empty_invalid_and_nonterminal_do_not_open_diff_or_undo(self):
        changes = self.journal()
        with patch("gemini_cli.client.change_view.diff_application") as view, \
             patch("gemini_cli.client.change_view.undo") as restore:
            for command in ("/diff", "/undo one name.py"):
                console = Mock(is_terminal=True)
                self.assertTrue(handle_change_command(command, None, console))
                self.assertIn("пока нет", str(console.print.call_args.args[0].renderable))
            console = Mock(is_terminal=False)
            self.assertTrue(handle_change_command("/diff proposed", changes, console))
            self.assertIn("интерактивный терминал", str(console.print.call_args.args[0].renderable))
            changes.resolve_path.side_effect = ValueError("Нет активных правок для этого файла")
            self.assertTrue(handle_change_command("/undo missing", changes, Mock(is_terminal=True)))
            view.assert_not_called()
            restore.assert_not_called()
        self.assertFalse(handle_change_command("/other", changes, Mock()))
        self.assertFalse(handle_change_command("", changes, Mock()))

    def test_pages_only_use_active_files_and_no_empty_preview(self):
        changes = self.journal()
        self.assertEqual(change_pages(changes, filepath="/workspace/proposed"),
                         [("proposed", "DIFF /workspace/proposed")])
        changes.active_files.return_value = {}
        self.assertEqual(change_pages(changes), [])
        self.assertEqual(change_pages(changes, filepath="/workspace/proposed"), [])

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

import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from gemini_cli.client.settings import Settings
from gemini_cli.client.secrets import SecretStore


class SettingsTest(unittest.TestCase):
    def test_selection_saved_without_keys_and_cancel_keeps_config(self):
        with tempfile.TemporaryDirectory() as root:
            secrets = SecretStore()
            secrets.set("gemini", "private")
            choices = Mock(side_effect=["local", None])
            settings = Settings(Path(root), remote_factory=Mock(), choose_mode=choices,
                                read_server=Mock(), choose_storage=Mock(), read_secret=Mock(), notify=Mock())
            with patch("gemini_cli.client.settings.configure_local", return_value=secrets):
                backend = settings.configure()
                before = settings.path.read_text()
                self.assertIsNone(settings.configure(force=True))
            self.assertEqual(backend.mode, "local")
            self.assertNotIn("private", before)
            self.assertEqual(settings.path.read_text(), before)
            settings.close()

    def test_switching_modes_restores_each_temporary_history(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"HOME": root}):
            ui = importlib.import_module("main")
        local, remote = Mock(mode="local"), Mock(mode="remote", base_url="https://one.test", account_id="a")
        for backend in (local, remote):
            backend.stream_chat.return_value.status_code = 200
        settings = Mock()
        settings.configure.side_effect = [local, remote, local]
        with patch.object(ui, "settings_controller", return_value=settings), \
                patch.object(ui, "show_chat_menu", return_value=(None, True)), \
                patch.object(ui, "print_banner"), patch.object(ui, "PromptSession") as prompt, \
                patch.object(ui, "display_stream_response", return_value=("answer", [])), \
                patch.object(ui.console, "print"), patch.object(ui.console, "rule"):
            prompt.return_value.prompt.side_effect = ["first", "/settings", "second", "/settings", "third", "exit"]
            ui.main()
        history = local.stream_chat.call_args.args[0]["history"]
        self.assertEqual([item["content"] for item in history], ["first", "answer"])
        self.assertEqual(remote.stream_chat.call_args.args[0]["history"], [])

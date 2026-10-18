import importlib
import json
import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class CommandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"HOME": home}):
            cls.client = importlib.import_module("main")

    def test_refusal_does_not_start_process(self):
        with (patch.object(self.client.console, "print"),
              patch("builtins.input", return_value="n"),
              patch("gemini_cli.tools.local.command.subprocess.run") as run):
            result = self.client.handle_execute_command({"command": "echo fixture"}, "/work")
        run.assert_not_called()
        self.assertIn("отменено пользователем", result)

    def test_command_output_and_execution_options(self):
        with (patch.object(self.client.console, "print"),
              patch("builtins.input", return_value="y"),
              patch("gemini_cli.tools.local.command.subprocess.run",
                    return_value=SimpleNamespace(returncode=3, stdout="out", stderr="err")) as run):
            result = json.loads(self.client.handle_execute_command({"command": " echo fixture "}, "/work"))
        run.assert_called_once_with("echo fixture", shell=True, cwd="/work", text=True,
                                    capture_output=True, timeout=120)
        self.assertEqual(result, {"exit_code": 3, "stdout": "out", "stderr": "err"})

    def test_timeout_returns_existing_error(self):
        with (patch.object(self.client.console, "print"),
              patch("builtins.input", return_value="y"),
              patch("gemini_cli.tools.local.command.subprocess.run",
                    side_effect=subprocess.TimeoutExpired("fixture", 120))):
            result = json.loads(self.client.handle_execute_command({"command": "fixture"}, "/work"))
        self.assertEqual(result, {"error": "Превышено время ожидания выполнения команды (Timeout 120s)"})

import importlib
import json
import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock


class CommandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"HOME": home}):
            cls.client = importlib.import_module("main")

    def test_refusal_does_not_start_process(self):
        with (patch.object(self.client.console, "print"),
              patch("builtins.input", return_value="n"),
              patch("gemini_cli.tools.local.command.ManagedProcess") as run):
            result = self.client.handle_execute_command({"command": "echo fixture"}, "/work")
        run.assert_not_called()
        self.assertIn("отменено пользователем", result)

    def test_command_output_and_execution_options(self):
        process = Mock(poll=Mock(return_value=3), wait=Mock(return_value="completed"))
        process.stdout.read.return_value, process.stderr.read.return_value = "out", "err"
        with (patch.object(self.client.console, "print"),
              patch("builtins.input", return_value="y"),
              patch("gemini_cli.tools.local.command.ManagedProcess", return_value=process) as run):
            result = json.loads(self.client.handle_execute_command({"command": " echo fixture "}, "/work"))
        run.assert_called_once_with("echo fixture", "/work")
        self.assertEqual(result, {"status": "completed", "exit_code": 3, "stdout": "out", "stderr": "err"})
        process.close.assert_called_once()


    def test_timeout_returns_existing_error(self):
        process = Mock(poll=Mock(return_value=-15), wait=Mock(return_value="timeout"))
        process.stdout.read.return_value = process.stderr.read.return_value = ""
        with (patch.object(self.client.console, "print"), patch("builtins.input", return_value="y"),
              patch("gemini_cli.tools.local.command.ManagedProcess", return_value=process)):
            result = json.loads(self.client.handle_execute_command({"command": "fixture"}, "/work"))
        self.assertEqual(result["status"], "timeout")
        process.close.assert_called_once()

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class CdCommandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"HOME": home}):
            cls.app = importlib.import_module("main")

    def test_relative_absolute_and_file_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "first" / "second"
            nested.mkdir(parents=True)
            absolute = root / "absolute"
            (absolute / "child").mkdir(parents=True)
            file_path = root / "file.txt"
            file_path.write_text("content", encoding="utf-8")

            commands = ["/cd first", "/cd second", f"/cd {absolute}",
                        f"/cd {file_path}", "/cd child", "exit"]
            with (patch.object(self.app.os, "getcwd", return_value=str(root)),
                  patch.object(self.app, "get_server_url", return_value="http://127.0.0.1:8000"),
                  patch.object(self.app, "GeminiAPIClient"),
                  patch.object(self.app, "show_chat_menu", return_value=(None, True)),
                  patch.object(self.app, "print_banner"),
                  patch.object(self.app, "PromptSession") as session,
                  patch.object(self.app.console, "print") as printed,
                  patch("builtins.input", side_effect=AssertionError("unexpected prompt"))):
                session.return_value.prompt.side_effect = commands
                self.app.main()

            output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
            for directory in (root / "first", nested, absolute, absolute / "child"):
                self.assertIn(f"Текущая папка сменена на: {directory}", output)
            self.assertIn(f"Путь '{file_path}' не является каталогом", output)
            self.assertNotIn(f"Текущая папка сменена на: {file_path}", output)


if __name__ == "__main__":
    unittest.main()

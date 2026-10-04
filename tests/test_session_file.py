import importlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class SessionFileTest(unittest.TestCase):
    def test_new_and_overwritten_session_remain_private_and_loadable(self):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"HOME": home}):
            client_module = importlib.import_module("main")
            directory = Path(home) / ".gemini_cli"
            session_file = directory / "session.json"

            with patch.object(client_module, "SESSION_FILE", str(session_file)):
                client_module.save_session({"access_token": "first"})
                self.assertEqual(client_module.GeminiAPIClient("http://localhost:8000")
                                 ._load_session_token(), "first")

                if os.name == "posix":
                    self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
                    self.assertEqual(stat.S_IMODE(session_file.stat().st_mode), 0o600)
                    os.chmod(directory, 0o755)
                    os.chmod(session_file, 0o644)

                client_module.save_session({"access_token": "second"})
                restarted_client = client_module.GeminiAPIClient("http://localhost:8000")
                self.assertEqual(restarted_client._load_session_token(), "second")
                self.assertEqual(json.loads(session_file.read_text(encoding="utf-8")),
                                 {"access_token": "second"})

                if os.name == "posix":
                    self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
                    self.assertEqual(stat.S_IMODE(session_file.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()

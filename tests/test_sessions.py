import os
import tempfile
import time
import unittest
from unittest.mock import Mock
from gemini_cli.client.sessions import SessionManager


class SessionTests(unittest.TestCase):
    def test_names_limit_stop_and_shutdown(self):
        factory = Mock(side_effect=lambda *a, **k: Mock(poll=Mock(return_value=None)))
        sessions = SessionManager(factory)
        try:
            with self.assertRaises(ValueError):
                sessions.start("../bad", ".")
            first = sessions.start("one", ".")
            self.assertIs(sessions.get("one"), first)
            with self.assertRaises(ValueError):
                sessions.start("one", ".")
            second = sessions.start("two", ".")
            self.assertEqual(sessions.list(), [("one", "running"), ("two", "running")])
            sessions.stop("one")
            first.close.assert_called_once()
            second.poll.return_value = 0
            self.assertEqual(sessions.list(), [("two", "exited")])
        finally:
            sessions.close()
        second.close.assert_called_once()

    @unittest.skipUnless(os.name == "posix", "POSIX shell")
    def test_live_shell_preserves_environment_and_directory(self):
        with tempfile.TemporaryDirectory() as cwd:
            sessions = SessionManager()
            try:
                first = sessions.start("live", cwd)
                first.write("export S3_VALUE=kept; cd /; printf 'READY:%%s:%%s\\n' \"$S3_VALUE\" \"$PWD\"\n".replace("%%", "%"))
                deadline = time.monotonic() + 3
                while "READY:kept:/" not in first.stdout.read() and time.monotonic() < deadline:
                    time.sleep(.03)
                self.assertIn("READY:kept:/", sessions.get("live").stdout.read())
                self.assertIsNone(first.poll())
            finally:
                sessions.close()
            self.assertIsNotNone(first.poll())

import os
from pathlib import Path
import stat
import tempfile
import unittest

from deploy.runtime_env import build_environment


class RuntimeEnvTest(unittest.TestCase):
    def test_allowlist_with_and_without_optional_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, destination = Path(temporary) / "input.env", Path(temporary) / "output.env"
            base = "API_KEY=fixture\nSUPABASE_URL=https://example.com\nSUPABASE_ANON_KEY=fixture\n"
            for optional in ("", "TAVILY_API_KEY=private-fixture\nSEARCH_PER_MINUTE=5\n"):
                source.write_text(base + optional + "UNRELATED_SECRET=must-not-copy\n")
                build_environment(source, destination)
                self.assertEqual(destination.read_text(), base + optional)
                if os.name == "posix":
                    self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)

    def test_missing_and_duplicate_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, destination = Path(temporary) / "input.env", Path(temporary) / "output.env"
            for content in ("", "API_KEY=a\nAPI_KEY=b\n"):
                source.write_text(content)
                with self.assertRaises(ValueError):
                    build_environment(source, destination)
                self.assertFalse(destination.exists())

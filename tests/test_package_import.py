import subprocess
import sys
import unittest
from pathlib import Path


class PackageImportTest(unittest.TestCase):
    def test_local_and_remote_do_not_import_server_dependencies(self):
        script = '''
import importlib.abc, sys, tempfile
from pathlib import Path
from unittest.mock import Mock
class BlockServer(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'main','server','fastapi','supabase','uvicorn'}:
            raise AssertionError('Server dependency: '+fullname)
sys.meta_path.insert(0, BlockServer())
from gemini_cli.backends.remote import RemoteBackend
http=Mock(); http.get.return_value.status_code=503
assert RemoteBackend('https://example.com', transport=http).get_chats() is None
assert 'google.genai' not in sys.modules
from gemini_cli.backends.local import LocalBackend
with tempfile.TemporaryDirectory() as root:
    backend=LocalBackend('fixture',Path(root))
    assert backend.get_chats()==[]
    backend.close()
assert 'google.genai' not in sys.modules
'''
        result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_import_without_environment_or_third_party_dependencies(self):
        project_dir = Path(__file__).resolve().parents[1]
        script = """
import importlib.abc
import sys
from pathlib import Path

class BlockApplicationImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {
            'main', 'server', 'fastapi', 'uvicorn', 'pydantic',
            'supabase', 'google', 'dotenv', 'requests', 'rich', 'prompt_toolkit',
        }:
            raise AssertionError('Unexpected dependency: ' + fullname)

sys.meta_path.insert(0, BlockApplicationImports())
import gemini_cli
from gemini_cli.tools.local import command, edit, files, search, workspace
from gemini_cli.client import tool_runner, web_tools, local_chats, profiles, secrets
from gemini_cli.backends import base, genai, local
from gemini_cli.runtime import history
from gemini_cli.tools import definitions, results
assert set(definitions.CLIENT_NAMES) == set(definitions.TOOLS)
assert Path(gemini_cli.__file__).resolve() == (
    Path.cwd() / 'gemini_cli' / '__init__.py'
).resolve()
assert Path(workspace.__file__).resolve() == (
    Path.cwd() / 'gemini_cli' / 'tools' / 'local' / 'workspace.py'
).resolve()
assert Path(files.__file__).resolve() == (
    Path.cwd() / 'gemini_cli' / 'tools' / 'local' / 'files.py'
).resolve()
"""
        result = subprocess.run(
            [sys.executable, "-B", "-S", "-c", script],
            cwd=project_dir,
            env={},
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()

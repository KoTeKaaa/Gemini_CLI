import subprocess
import sys
import unittest


class BackendImportsTest(unittest.TestCase):
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
from gemini_cli.integrations.mcp.manager import Manager
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


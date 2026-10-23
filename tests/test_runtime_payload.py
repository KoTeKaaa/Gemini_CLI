import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.runtime_payload import install_runtime


class RuntimePayloadTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.destination = self.root / "installed"
        self.write(self.source, "server.py", "app = 'fixture'\n")
        self.write(self.source, "gemini_cli/__init__.py", "")
        self.helper = Path(__file__).resolve().parents[1] / "deploy/runtime_payload.py"

    def write(self, root, relative, content="excluded"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def install(self, destination=None, success=True):
        result = subprocess.run(
            [sys.executable, "-B", str(self.helper), str(self.source),
             str(destination or self.destination)],
            capture_output=True, text=True, timeout=15,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)

    def test_only_runtime_python_is_delivered(self):
        self.write(self.source, "gemini_cli/server/__init__.py", "")
        self.write(self.source, "gemini_cli/server/routes.py", "value = 1\n")
        for name in (
            ".env", "key.pem", "tests/test_server.py", "main.py",
            "gemini_cli/.env", "gemini_cli/key.pem", "gemini_cli/key.key",
            "gemini_cli/__pycache__/old.py", "gemini_cli/tests/helper.py",
            "gemini_cli/test_routes.py", "gemini_cli/routes_test.py",
            "gemini_cli/conftest.py", "gemini_cli/.private/config.py",
        ):
            self.write(self.source, name)
        self.install()
        delivered = {str(path.relative_to(self.destination))
                     for path in self.destination.rglob("*") if path.is_file()}
        self.assertEqual(delivered, {
            "server.py", "gemini_cli/__init__.py", "gemini_cli/server/__init__.py",
            "gemini_cli/server/routes.py",
        })
        self.assertEqual((self.destination / "gemini_cli/server/routes.py")
                         .read_text(encoding="utf-8"), "value = 1\n")

    def test_actual_server_payload_imports_without_client_code_or_network(self):
        repository = Path(__file__).resolve().parents[1]
        install_runtime(repository, self.destination)
        self.assertTrue((self.destination / "gemini_cli/backends/model_info.py").is_file())
        self.assertFalse((self.destination / "gemini_cli/client").exists())
        self.assertFalse((self.destination / "gemini_cli/integrations").exists())
        self.assertFalse((self.destination / "gemini_cli/backends/remote.py").exists())
        smoke = """
import pathlib
import sys
def deny_network(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto'}:
        raise AssertionError('Payload import attempted network access')
sys.addaudithook(deny_network)
sys.path.insert(0, sys.argv[1])
import server
assert pathlib.Path(server.__file__).resolve() == pathlib.Path(sys.argv[1]) / 'server.py'
assert not any(name == 'gemini_cli.client' or name.startswith('gemini_cli.client.') for name in sys.modules)
assert {'/chat/context', '/chat/compact', '/chat/summary'} <= {getattr(route, 'path', None) for route in server.app.routes}
assert server.deployment_health()['status'] == 'ok'
server.client.close()
"""
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", smoke, str(self.destination)],
            cwd=self.destination, capture_output=True, text=True, timeout=20,
            env={"API_KEY": "fixture", "SUPABASE_URL": "https://example.supabase.co",
                 "SUPABASE_ANON_KEY": "fixture", "ADMIN_SESSION_SECRET": "fixture",
                 "HOME": str(self.root), "PYTHON_DOTENV_DISABLED": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_declared_panel_asset_locations_are_copied(self):
        for name in ("gemini_cli/server/admin/templates/login.html", "gemini_cli/server/admin/static/panel.js",
                     "gemini_cli/server/admin/static/panel.css"):
            self.write(self.source, name, "asset")
        self.write(self.source, "gemini_cli/client/private.html", "private")
        self.write(self.source, "gemini_cli/server/admin/static/private.json", "secret")
        self.write(self.source, "gemini_cli/client/secrets.py", "private")
        self.write(self.source, "gemini_cli/backends/remote.py", "unneeded")
        self.write(self.source, "gemini_cli/backends/genai.py", "provider")
        self.install()
        self.assertEqual((self.destination / "gemini_cli/server/admin/templates/login.html").read_text(), "asset")
        self.assertFalse((self.destination / "gemini_cli/client/private.html").exists())
        self.assertFalse((self.destination / "gemini_cli/server/admin/static/private.json").exists())
        self.assertFalse((self.destination / "gemini_cli/client/secrets.py").exists())
        self.assertFalse((self.destination / "gemini_cli/backends/remote.py").exists())
        self.assertTrue((self.destination / "gemini_cli/backends/genai.py").exists())

    def test_reinstall_removes_stale_package_only(self):
        old = self.write(self.source, "gemini_cli/server/obsolete.py", "old = 1\n")
        self.install()
        old.unlink()
        self.write(self.source, "server.py", "app = 'updated'\n")
        for name in (".env", ".venv/marker", "other/keep.py", "requirements-server.txt"):
            self.write(self.destination, name, "preserved")
        self.install()
        self.assertFalse((self.destination / "gemini_cli/server/obsolete.py").exists())
        self.assertEqual((self.destination / "server.py").read_text(), "app = 'updated'\n")
        for name in (".env", ".venv/marker", "other/keep.py", "requirements-server.txt"):
            self.assertEqual((self.destination / name).read_text(), "preserved")
        self.assertEqual(list(self.destination.glob(".runtime-*")), [])

    def test_in_place_install(self):
        self.write(self.source, ".env", "preserved")
        self.install(destination=self.source)
        self.assertTrue((self.source / "gemini_cli/__init__.py").is_file())
        self.assertEqual((self.source / ".env").read_text(), "preserved")

    def test_source_links_are_not_delivered(self):
        outside = self.write(self.root, "outside/secret.py")
        (self.source / "gemini_cli/linked.py").symlink_to(outside)
        (self.source / "gemini_cli/linked_dir").symlink_to(outside.parent, target_is_directory=True)
        self.install()
        self.assertFalse((self.destination / "gemini_cli/linked.py").exists())
        self.assertFalse((self.destination / "gemini_cli/linked_dir").exists())

    def test_target_link_is_rejected_without_touching_outside(self):
        outside = self.write(self.root, "outside/keep.py", "preserved")
        self.destination.mkdir()
        (self.destination / "gemini_cli").symlink_to(outside.parent, target_is_directory=True)
        self.install(success=False)
        self.assertEqual(outside.read_text(), "preserved")

    def test_incomplete_source_keeps_installed_package(self):
        self.install()
        (self.source / "gemini_cli/__init__.py").unlink()
        self.install(success=False)
        self.assertTrue((self.destination / "gemini_cli/__init__.py").is_file())

    def test_failed_server_replace_restores_previous_package(self):
        self.write(self.source, "gemini_cli/previous.py", "previous = True\n")
        self.install()
        (self.source / "gemini_cli/previous.py").unlink()
        self.write(self.source, "server.py", "app = 'updated'\n")
        with patch("deploy.runtime_payload.os.replace", side_effect=OSError("write failed")):
            with self.assertRaisesRegex(OSError, "write failed"):
                install_runtime(self.source, self.destination)
        self.assertTrue((self.destination / "gemini_cli/previous.py").is_file())
        self.assertEqual((self.destination / "server.py").read_text(), "app = 'fixture'\n")
        self.assertEqual(list(self.destination.glob(".runtime-*")), [])


if __name__ == "__main__":
    unittest.main()

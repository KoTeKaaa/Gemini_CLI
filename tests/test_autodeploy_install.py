from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from types import SimpleNamespace
from deploy.enable_autodeploy import install


class AutodeployInstallTest(unittest.TestCase):
    def test_installer_preserves_env_and_current_release_override(self):
        source = Path(__file__).resolve().parents[1] / 'deploy'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = root / 'etc/gemini-cli/server.env'
            env.parent.mkdir(parents=True)
            original = b'API_KEY=private\r\nCUSTOM_KEY=retained\n'
            env.write_bytes(original); env.chmod(0o600)
            previous = root / 'etc/systemd/system/gemini-cli.service.d/10-release.conf'
            previous.parent.mkdir(parents=True)
            previous.write_bytes(b'existing release')
            execute = Mock(return_value=SimpleNamespace(returncode=3))
            install(source, root, 'owner/repo', execute=execute)
            self.assertEqual(env.read_bytes(), original)
            self.assertEqual(previous.read_bytes(), b'existing release')
            config = root / 'etc/gemini-cli/deploy.json'
            self.assertNotIn('private', config.read_text())
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            execute.assert_any_call(['systemctl', 'enable', '--now', 'gemini-cli-autodeploy.timer'])

    def test_active_deployment_prevents_reconfiguration(self):
        source = Path(__file__).resolve().parents[1] / 'deploy'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = root / 'etc/gemini-cli/server.env'
            env.parent.mkdir(parents=True); env.write_bytes(b'keep'); env.chmod(0o600)
            with self.assertRaisesRegex(ValueError, 'active'):
                install(source, root, 'owner/repo', execute=Mock(return_value=SimpleNamespace(returncode=0)))
            self.assertFalse((root / 'etc/gemini-cli/deploy.json').exists())

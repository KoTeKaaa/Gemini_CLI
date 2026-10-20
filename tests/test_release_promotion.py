from pathlib import Path
import os
import shutil
import tempfile
import unittest
from unittest.mock import Mock
from deploy.promote import promote_release


class ReleasePromotionTest(unittest.TestCase):
    def fixture(self, root):
        base = Path(root)
        env = base / 'server.env'; env.write_bytes(b'API_KEY=do-not-rewrite\nCUSTOM_SECRET=keep\r\n')
        return dict(env=str(env), override=str(base / 'override.conf'), state=str(base / 'state'),
                    user='gemini-cli', service='gemini-cli.service')

    def test_success_retains_env_and_records_exact_revision(self):
        with tempfile.TemporaryDirectory() as root:
            config = self.fixture(root)
            before = Path(config['env']).read_bytes()
            promote_release(config, Path(root) / 'release', 'a' * 40, run=Mock(), probe=Mock(return_value=True))
            self.assertEqual(Path(config['env']).read_bytes(), before)
            self.assertIn('a' * 40, (Path(config['state']) / 'state.json').read_text())
            self.assertIn('GEMINI_RELEASE_SHA=', Path(config['override']).read_text())

    def test_candidate_failure_never_changes_service_override_or_env(self):
        with tempfile.TemporaryDirectory() as root:
            config = self.fixture(root)
            Path(config['override']).write_bytes(b'original')
            with self.assertRaisesRegex(RuntimeError, 'Candidate'):
                promote_release(config, Path(root), 'a' * 40, run=Mock(), probe=Mock(return_value=False))
            self.assertEqual(Path(config['override']).read_bytes(), b'original')
            self.assertIn(b'CUSTOM_SECRET=keep\r\n', Path(config['env']).read_bytes())

    def test_failed_production_restores_prior_override(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as root:
                config = self.fixture(root)
                override = Path(config['override'])
                if existing:
                    override.write_bytes(b'[Service]\nWorkingDirectory=/previous\n')
                probe = Mock(side_effect=[True, False, True])
                with self.assertRaisesRegex(RuntimeError, 'Production'):
                    promote_release(config, Path(root), 'a' * 40, run=Mock(), probe=probe)
                self.assertEqual(override.read_bytes() if override.exists() else None,
                                 b'[Service]\nWorkingDirectory=/previous\n' if existing else None)
                self.assertFalse((Path(config['state']) / 'state.json').exists())

    def test_concurrent_env_rotation_is_preserved_and_aborts_switch(self):
        with tempfile.TemporaryDirectory() as root:
            config = self.fixture(root)
            def preview(*args):
                Path(config['env']).write_bytes(b'API_KEY=rotated-by-owner\n')
                return True
            with self.assertRaisesRegex(RuntimeError, 'Environment changed'):
                promote_release(config, Path(root), 'a' * 40, run=Mock(), probe=preview)
            self.assertEqual(Path(config['env']).read_bytes(), b'API_KEY=rotated-by-owner\n')
            self.assertFalse(Path(config['override']).exists())

    @unittest.skipUnless(os.name == "posix", "Release promotion requires Linux runuser")
    def test_staging_under_private_umask_keeps_runtime_readable(self):
        import io
        import os
        import tarfile
        from unittest.mock import patch
        from deploy.promote import prepare_release
        with tempfile.TemporaryDirectory() as root:
            state = Path(root) / 'state'; state.mkdir()
            config = dict(state=str(state), releases=str(Path(root) / 'releases'),
                          repository='owner/repo', user='gemini-cli')
            # Model the VPS layout: runuser exists in sbin, not in bin.
            tools = state / 'tools'
            (tools / 'sbin').mkdir(parents=True)
            (tools / 'bin').mkdir()
            runuser = tools / 'sbin/runuser'
            runuser.write_text('#!/bin/sh\nexit 0\n')
            runuser.chmod(0o755)
            pip_calls = []
            def command(args, **kwargs):
                if args[0] == 'runuser':
                    environment = kwargs['env']
                    # subprocess resolves runuser using this exact clean env,
                    # before it can drop privileges and launch the venv Python.
                    fixture_path = os.pathsep.join(str(tools / Path(folder).name)
                                                   for folder in environment['PATH'].split(os.pathsep))
                    resolved = shutil.which(args[0], path=fixture_path)
                    self.assertIsNotNone(resolved, 'Sanitized PATH must resolve runuser')
                    self.assertEqual(Path(resolved), runuser)
                    self.assertTrue(os.access(resolved, os.X_OK))
                    self.assertEqual(args[:4], ['runuser', '-u', config['user'], '--'])
                    self.assertEqual(set(environment), {'PATH', 'LANG', 'PYTHONDONTWRITEBYTECODE'})
                    self.assertNotIn('/untrusted/operator/bin', environment['PATH'].split(os.pathsep))
                    self.assertNotIn('PRIVATE_FIXTURE', str(environment))
                    pip_calls.append(args)
                if 'archive' in args:
                    output = next(value.split('=', 1)[1] for value in args if value.startswith('--output='))
                    with tarfile.open(output, 'w') as bundle:
                        for name in ('server.py', 'gemini_cli/__init__.py', 'deploy/requirements-server.txt'):
                            info = tarfile.TarInfo(name); info.size = 1
                            bundle.addfile(info, io.BytesIO(b'\n'))
            previous = os.umask(0o077)
            try:
                with patch.dict(os.environ, {'PATH': '/untrusted/operator/bin',
                                             'API_KEY': 'PRIVATE_FIXTURE', 'PIP_INDEX_URL': 'PRIVATE_FIXTURE'}), \
                     patch('deploy.promote.command', side_effect=command), \
                     patch('deploy.promote.subprocess.check_output', return_value=b'a' * 40):
                    release = prepare_release(config, 'a' * 40)
            finally:
                os.umask(previous)
            self.assertEqual(len(pip_calls), 2)
            self.assertEqual(pip_calls[0][4:8], [str(release / '.venv/bin/python'), '-m', 'pip', 'install'])
            self.assertEqual(pip_calls[1][4:], [str(release / '.venv/bin/python'), '-m', 'pip', 'check'])
            self.assertEqual(Path(config['releases']).stat().st_mode & 0o777, 0o755)
            self.assertEqual(release.stat().st_mode & 0o777, 0o755)
            self.assertEqual((release / 'requirements-server.txt').stat().st_mode & 0o777, 0o644)

    def test_cleanup_keeps_active_rollback_and_unmanaged_releases(self):
        from unittest.mock import patch
        from deploy.promote import clean_releases
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            releases = root / 'releases'; releases.mkdir()
            active = releases / ('a' * 40 + '-12345678'); active.mkdir()
            rollback = releases / ('b' * 40 + '-12345678'); rollback.mkdir()
            abandoned = releases / ('c' * 40 + '-12345678'); abandoned.mkdir()
            old = releases / 's0-existing'; old.mkdir()
            link = releases / ('d' * 40 + '-12345678'); link.symlink_to(old)
            (root / 'previous-override.conf').write_text(f'[Service]\nWorkingDirectory={rollback}\n')
            config = dict(service='example.service', state=str(root), releases=str(releases))
            with patch('deploy.promote.subprocess.check_output', return_value=str(active).encode()):
                clean_releases(config)
            self.assertFalse(abandoned.exists())
            self.assertTrue(all(path.exists() for path in (active, rollback, old, link)))
            with patch('deploy.promote.subprocess.check_output', return_value=b''):
                with self.assertRaisesRegex(RuntimeError, 'identify active'):
                    clean_releases(config)
            self.assertTrue(active.exists())

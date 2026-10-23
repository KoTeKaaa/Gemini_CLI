import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from gemini_cli.tools.local.git_tools import git_read


def git(root, *args):
    return subprocess.check_output(['git', '-C', root, *args], stderr=subprocess.STDOUT).decode()


def repository(root):
    git(root, 'init', '-q')
    git(root, 'config', 'user.email', 'fixture@example.com'); git(root, 'config', 'user.name', 'Fixture')
    Path(root, 'a.py').write_text('x=1\n')
    git(root, 'add', 'a.py'); git(root, 'commit', '-qm', 'Initial')


class GitToolsTests(unittest.TestCase):
    def test_dirty_untracked_rename_and_read_preserves_index(self):
        with tempfile.TemporaryDirectory() as root:
            repository(root)
            git(root, 'mv', 'a.py', 'renamed.py')
            Path(root, 'renamed.py').write_text('x=2\n')
            Path(root, 'new.py').write_text('new=1\n')
            before = Path(root, '.git/index').read_bytes()
            branch = git(root, 'symbolic-ref', 'HEAD')
            def read(action, **extra):
                return git_read({'action': action, 'files': ['a.py', 'renamed.py', 'new.py'], **extra}, root, approve=lambda _: True)
            entries = read('status')['data']['entries']
            self.assertTrue(any(row['index'] == 'R' for row in entries))
            self.assertTrue(any(row['index'] == '?' for row in entries))
            self.assertIn('+x=2', read('diff')['data']['stdout'])
            self.assertEqual(read('log')['status'], 'ok')
            self.assertEqual(before, Path(root, '.git/index').read_bytes())
            self.assertEqual(branch, git(root, 'symbolic-ref', 'HEAD'))

    def test_blame_errors_missing_git_and_sensitive_path(self):
        with tempfile.TemporaryDirectory() as root:
            repository(root)
            args = {'action': 'blame', 'files': ['a.py'], 'end_line': 1}
            self.assertEqual(git_read(args, root, approve=lambda _: True)['status'], 'ok')
            with patch('gemini_cli.tools.local.git_tools.ManagedProcess', side_effect=FileNotFoundError):
                self.assertEqual(git_read(args, root, approve=lambda _: True)['status'], 'error')
            args['files'] = ['.env']
            self.assertEqual(git_read(args, root, approve=lambda _: True)['status'], 'error')

import tempfile
import unittest
from pathlib import Path
from gemini_cli.tools.local.git_commit import git_commit
from tests.test_git_tools import git, repository


class GitCommitTests(unittest.TestCase):
    def test_only_selection_preserves_unrelated_staged_and_worktree(self):
        with tempfile.TemporaryDirectory() as root:
            repository(root)
            other = Path(root, 'other.py'); other.write_text('staged=1\n')
            git(root, 'add', 'other.py'); other.write_text('unstaged=2\n')
            Path(root, 'a.py').write_text('x=2\n')
            Path(root, 'new.py').write_text('new=1\n')
            result = git_commit({'action': 'prepare', 'files': ['a.py', 'new.py'], 'message': 'Change x', 'task': 'fixture'},
                                root, approve=lambda _: True)
            token = result['data']['token']
            result = git_commit({'action': 'commit', 'token': token}, root, approve=lambda _: True)
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(git(root, 'show', 'HEAD:a.py'), 'x=2\n')
            self.assertEqual(git(root, 'show', 'HEAD:new.py'), 'new=1\n')
            self.assertEqual(git(root, 'show', ':other.py'), 'staged=1\n')
            self.assertEqual(other.read_text(), 'unstaged=2\n')
            self.assertEqual(git_commit({'action': 'commit', 'token': token}, root, approve=lambda _: True)['status'], 'error')

    def test_changed_diff_denial_and_hook_error(self):
        with tempfile.TemporaryDirectory() as root:
            repository(root)
            file = Path(root, 'a.py'); file.write_text('x=2\n')
            def prepare():
                return git_commit({'action': 'prepare', 'files': ['a.py'], 'message': 'Change x'},
                                  root, approve=lambda _: True)['data']['token']
            token = prepare(); file.write_text('x=3\n')
            self.assertEqual(git_commit({'action': 'commit', 'token': token}, root, approve=lambda _: True)['error']['code'], 'conflict')
            hook = Path(root, '.git/hooks/pre-commit')
            hook.write_text('#!/bin/sh\necho fixture-hook-failed >&2\nexit 1\n'); hook.chmod(0o755)
            result = git_commit({'action': 'commit', 'token': prepare()}, root, approve=lambda _: True)
            self.assertEqual(result['error']['code'], 'git_error')
            self.assertIn('fixture-hook-failed', result['data']['stderr'])
            self.assertEqual(git(root, 'show', 'HEAD:a.py'), 'x=1\n')

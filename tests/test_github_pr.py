import json
import tempfile
import unittest
from gemini_cli.integrations.github_pr import github_pr
from gemini_cli.protocol.mcp import tool_name
from tests.test_git_tools import git, repository


class Manager:
    enabled = {'github'}
    def __init__(self):
        self.existing, self.calls, self.fail = [], [], False
    def declarations(self):
        return [{'name': tool_name('github', n)} for n in
                ('list_pull_requests', 'create_pull_request', 'update_pull_request', 'pull_request_read')]
    def call(self, name, args, **kwargs):
        self.calls.append((name, args))
        if self.fail: return json.dumps({'isError': True, 'content': [{'text': '401/no permission'}]})
        if name == tool_name('github', 'list_pull_requests'): value = self.existing
        elif name == tool_name('github', 'create_pull_request'):
            self.existing = [{'number': 5, 'head': {'ref': 'feature/test'}, 'base': {'ref': 'dev'}}]
            value = {'number': 5}
        else: value = {'state': 'pending'}
        return json.dumps({'content': [{'type': 'text', 'text': json.dumps(value)}], 'isError': False})


class PRTests(unittest.TestCase):
    def test_create_repeat_update_and_checks(self):
        with tempfile.TemporaryDirectory() as root:
            repository(root); git(root, 'switch', '-qc', 'feature/test')
            git(root, 'remote', 'add', 'origin', 'git@github.com:Example/repo.git')
            manager = Manager()
            def call(action):
                return github_pr({'action': action, 'title': 'Fix parser', 'body': 'Fix and checks', 'base': 'dev'},
                                 root, manager=manager, approve=lambda *_: True)
            self.assertEqual(call('create')['data']['url'], 'https://github.com/Example/repo/pull/5')
            self.assertTrue(call('create')['data']['existing'])
            self.assertEqual(sum(n == tool_name('github', 'create_pull_request') for n, _ in manager.calls), 1)
            self.assertEqual(call('update')['status'], 'ok')
            self.assertEqual(call('checks')['data']['checks']['state'], 'pending')
            self.assertFalse(any('merge' in str(args) for _, args in manager.calls))
            manager.fail = True
            self.assertEqual(call('create')['error']['code'], 'pr_error')

    def test_no_remote_disabled_and_missing_permissions(self):
        with tempfile.TemporaryDirectory() as root:
            repository(root); manager = Manager()
            self.assertEqual(github_pr({'action': 'create'}, root, manager=manager,
                                      approve=lambda *_: True)['status'], 'error')
            self.assertEqual(github_pr({'action': 'create'}, root, manager=None,
                                      approve=lambda *_: True)['error']['code'], 'mcp_disabled')

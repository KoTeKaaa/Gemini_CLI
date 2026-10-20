import unittest
from unittest.mock import Mock
from deploy.verified_main import verified_main

REPO = 'owner/repo'
SHA = 'a' * 40


def metadata(conclusion='success', source='dev'):
    run = dict(id=7, run_number=1, head_sha=SHA, head_branch='main', event='push',
               repository={'full_name': REPO}, status='completed', conclusion=conclusion)
    pull = dict(merged_at='now', merge_commit_sha=SHA, base={'ref': 'main', 'repo': {'full_name': REPO}},
                head={'ref': source, 'repo': {'full_name': REPO}})
    return [{'object': {'sha': SHA}}, {'workflow_runs': [run]},
            {'jobs': [{'name': 'production-ready', 'status': 'completed', 'conclusion': 'success'}]},
            [pull], {'object': {'sha': SHA}}]


class VerifiedMainTest(unittest.TestCase):
    def test_deploys_only_verified_exact_main_merge(self):
        api = Mock(); api.get.side_effect = metadata()
        self.assertEqual(verified_main(api, REPO), SHA)

    def test_failure_pending_and_missing_workflow_do_not_deploy(self):
        for conclusion in ('failure', None, 'skipped', 'cancelled'):
            api = Mock(); api.get.side_effect = metadata(conclusion)
            self.assertIsNone(verified_main(api, REPO))
        api = Mock(); api.get.side_effect = [{'object': {'sha': SHA}}, None]
        self.assertIsNone(verified_main(api, REPO))

    def test_wrong_origin_missing_gate_and_newer_main_are_rejected(self):
        cases = [metadata(source='feature/test'), metadata(), metadata(), metadata()]
        cases[1][2]['jobs'] = []
        cases[2][-1]['object']['sha'] = 'b' * 40
        cases[3][3][0]['head']['repo']['full_name'] = 'fork/repo'
        for values in cases:
            api = Mock(); api.get.side_effect = values
            self.assertIsNone(verified_main(api, REPO))

    def test_installed_revision_does_not_poll_actions(self):
        api = Mock(); api.get.return_value = {'object': {'sha': SHA}}
        self.assertIsNone(verified_main(api, REPO, installed=SHA))
        api.get.assert_called_once()

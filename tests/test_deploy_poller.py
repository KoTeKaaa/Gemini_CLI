from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from deploy.poller import run_once


class DeployPollerTest(unittest.TestCase):
    def test_missing_or_failed_ci_never_builds_or_promotes(self):
        with tempfile.TemporaryDirectory() as root, patch('deploy.poller.verified_main', return_value=None):
            build, promote = Mock(), Mock()
            config = dict(state=root, repository='owner/repo')
            self.assertIsNone(run_once(config, api=Mock(), build=build, promote=promote, cleanup=Mock()))
            build.assert_not_called(); promote.assert_not_called()

    def test_check_only_never_changes_production(self):
        with tempfile.TemporaryDirectory() as root, patch('deploy.poller.verified_main', return_value='a' * 40):
            build, promote = Mock(), Mock()
            config = dict(state=root, repository='owner/repo')
            self.assertEqual(run_once(config, check=True, api=Mock(), build=build, promote=promote, cleanup=Mock()), 'a' * 40)
            build.assert_not_called(); promote.assert_not_called()

    def test_newer_main_after_staging_prevents_promotion(self):
        with tempfile.TemporaryDirectory() as root, patch('deploy.poller.verified_main', side_effect=['a' * 40, None]):
            promote = Mock()
            config = dict(state=root, repository='owner/repo')
            self.assertIsNone(run_once(config, api=Mock(), build=Mock(return_value=Path(root)), promote=promote, cleanup=Mock()))
            promote.assert_not_called()

    def test_verified_revision_is_promoted(self):
        with tempfile.TemporaryDirectory() as root, patch('deploy.poller.verified_main', return_value='a' * 40):
            promote = Mock()
            config = dict(state=root, repository='owner/repo')
            self.assertEqual(run_once(config, api=Mock(), build=Mock(return_value=Path(root)), promote=promote, cleanup=Mock()), 'a' * 40)
            promote.assert_called_once_with(config, Path(root), 'a' * 40)

    def test_build_failure_still_cleans_candidates(self):
        with tempfile.TemporaryDirectory() as root, patch('deploy.poller.verified_main', return_value='a' * 40):
            cleanup = Mock()
            with self.assertRaisesRegex(RuntimeError, 'pip failed'):
                run_once(dict(state=root, repository='owner/repo'), api=Mock(),
                         build=Mock(side_effect=RuntimeError('pip failed')), cleanup=cleanup)
            self.assertEqual(cleanup.call_count, 2)

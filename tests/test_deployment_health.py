import importlib
import os
import unittest
from unittest.mock import patch


class DeploymentHealthTest(unittest.TestCase):
    def test_health_contains_only_status_and_boot_revision(self):
        with patch.dict(os.environ, {'API_KEY': 'fixture', 'SUPABASE_URL': 'https://example.supabase.co',
                                     'SUPABASE_ANON_KEY': 'fixture'}):
            server = importlib.import_module('server')
        with patch.object(server, 'DEPLOYMENT_REVISION', 'a' * 40):
            self.assertEqual(server.deployment_health(), {'status': 'ok', 'revision': 'a' * 40})

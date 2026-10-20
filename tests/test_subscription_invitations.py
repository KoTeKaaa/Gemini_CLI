import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from gemini_cli.server.admin.invitations import InvitationInput, issue_invitation, token_hash


class InvitationTest(unittest.TestCase):
    def test_only_hash_sent_to_db_and_secret_only_in_fragment(self):
        db = Mock()
        db.rpc.return_value.execute.return_value.data = "invite"
        with patch.dict(os.environ, {"ADMIN_ORIGIN": "https://panel.test"}), patch(
            "gemini_cli.server.admin.invitations.safe_admin_call", side_effect=lambda call: call(db)
        ):
            result = issue_invitation(SimpleNamespace(user_id="owner"),
                                      InvitationInput(subscription_id=uuid4()))
        token = result["url"].split("#")[1]
        self.assertGreaterEqual(len(token), 40)
        args = db.rpc.call_args.args[1]
        self.assertEqual(args["secret_hash"], token_hash(token))
        self.assertNotIn(token, str(args))
        self.assertNotIn("?", result["url"])

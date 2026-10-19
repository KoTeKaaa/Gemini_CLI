import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gemini_cli.backends.local import LocalBackend
from gemini_cli.client.web_tools import ToolTurn


class LocalWebTest(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.backend = LocalBackend("gemini-private", Path(root.name))

    def test_optional_personal_key_and_no_server_fallback(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": "server-key"}), patch(
            "gemini_cli.tools.web.search.search", return_value={"status": "ok"}
        ) as search:
            self.assertEqual(self.backend.web_tool("search", {"query": "q"})["status"], "error")
            search.assert_not_called()
            self.backend.tavily_key = "personal"
            self.backend.web_tool("search", {"query": "q"})
            self.assertEqual(search.call_args.kwargs["api_key"], "personal")

    def test_shared_turn_budget_is_three_without_retries(self):
        self.backend.tavily_key = "personal"
        with patch("gemini_cli.tools.web.search.search", return_value={"status": "ok"}) as search:
            turn = ToolTurn()
            for index in range(4):
                result = json.loads(turn.search({"query": str(index)}, self.backend.web_tool))
            self.assertEqual(search.call_count, 3)
            self.assertEqual(result["error"]["code"], "budget")

    def test_read_url_needs_no_tavily_and_rejects_private_address(self):
        result = self.backend.web_tool("read", {"url": "http://127.0.0.1"})
        self.assertEqual(result["status"], "error")

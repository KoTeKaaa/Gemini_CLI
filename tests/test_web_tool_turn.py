import json
import unittest
from unittest.mock import Mock

from gemini_cli.client.web_tools import ToolTurn


class WebToolTurnTest(unittest.TestCase):
    def test_budget_and_cache_cover_multiple_batches_and_reset(self):
        request = Mock(return_value={"status": "ok", "data": {"results": []}})
        turn = ToolTurn()
        first = turn.search({"query": "one"}, request)
        self.assertEqual(turn.search({"query": "one"}, request), first)
        for query in ("two", "three", "four"):
            result = json.loads(turn.search({"query": query}, request))
        self.assertEqual(request.call_count, 3)
        self.assertEqual(result["error"]["code"], "budget")
        self.assertFalse(turn.search_available)
        ToolTurn().search({"query": "four"}, request)
        self.assertEqual(request.call_count, 4)

    def test_failed_search_is_cached_and_disabled(self):
        for code in ("network", "quota", "timeout", "unavailable"):
            request = Mock(return_value={"status": "error", "error": {"code": code}})
            turn = ToolTurn()
            turn.search({"query": "one"}, request)
            turn.search({"query": "one"}, request)
            turn.search({"query": "two"}, request)
            request.assert_called_once()

import json
import unittest
from unittest.mock import MagicMock, patch

import requests
from gemini_cli.tools.web.search import search


class WebSearchTest(unittest.TestCase):
    def request(self, status=200, payload=None, error=None):
        session = MagicMock()
        response = session.post.return_value
        response.status_code = status
        response.json.return_value = payload if payload is not None else {"results": []}
        if error:
            session.post.side_effect = error
        with patch("gemini_cli.tools.web.search.requests.Session") as factory:
            factory.return_value.__enter__.return_value = session
            result = search("documentation", api_key="PRIVATE-KEY")
        self.assertNotIn("PRIVATE-KEY", json.dumps(result))
        return result, session

    def test_empty_and_successful_results_and_basic_parameters(self):
        result, session = self.request(payload={"results": [
            {"title": "Docs", "url": "https://example.com", "content": "Text"}]})
        self.assertEqual(result["data"]["results"][0]["snippet"], "Text")
        parameters = session.post.call_args.kwargs
        self.assertEqual(parameters["json"]["search_depth"], "basic")
        self.assertIs(parameters["json"]["auto_parameters"], False)
        self.assertEqual(parameters["json"]["max_results"], 5)
        self.assertFalse(session.trust_env)
        self.assertEqual(self.request()[0]["data"]["results"], [])

    def test_errors_do_not_leak_or_retry(self):
        for status, code in ((401, "unavailable"), (429, "quota"), (432, "quota"), (500, "provider_error")):
            with self.subTest(status=status):
                result, session = self.request(status)
                self.assertEqual(result["error"]["code"], code)
                session.post.assert_called_once()
        result, session = self.request(error=requests.Timeout("PRIVATE-KEY"))
        self.assertEqual(result["error"]["code"], "timeout")
        session.post.assert_called_once()
        self.assertEqual(self.request(payload={"results": "invalid"})[0]["error"]["code"], "invalid_response")

    def test_missing_key_and_invalid_parameters_do_not_request(self):
        with patch("gemini_cli.tools.web.search.requests.Session") as factory:
            self.assertEqual(search("q", api_key=None)["error"]["code"], "unavailable")
            self.assertEqual(search("", api_key="key")["error"]["code"], "invalid_arguments")
            self.assertEqual(search("q", 6, api_key="key")["error"]["code"], "invalid_arguments")
        factory.assert_not_called()

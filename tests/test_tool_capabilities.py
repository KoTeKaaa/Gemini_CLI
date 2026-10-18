import unittest

from gemini_cli.tools.definitions import LEGACY_NAMES, available_tools
from gemini_cli.tools.results import failure, success


class ToolCapabilitiesTest(unittest.TestCase):
    def test_legacy_request_retains_three_tools(self):
        self.assertEqual(tuple(tool.__name__ for tool in available_tools(None)), LEGACY_NAMES)

    def test_intersection_excludes_unknown_and_disabled(self):
        tools = available_tools(["read_local_files", "execute_command", "unknown"],
                                {"read_local_files", "unknown"})
        self.assertEqual([tool.__name__ for tool in tools], ["read_local_files"])
        self.assertEqual(available_tools([]), [])

    def test_new_results_distinguish_success_and_failure(self):
        self.assertEqual(success({"items": []}),
                         {"status": "ok", "data": {"items": []}, "truncated": False})
        self.assertEqual(failure("unavailable", "Unavailable")["error"]["code"], "unavailable")

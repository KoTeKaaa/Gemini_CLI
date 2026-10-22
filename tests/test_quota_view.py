from threading import Event
import unittest
from unittest.mock import Mock
import os
import tempfile

from prompt_toolkit.utils import get_cwidth

from gemini_cli.client.quota_view import limits_text, status_line, PromptStatus, shorten


class QuotaViewTests(unittest.TestCase):
    def test_width_unicode_and_untrusted_names(self):
        for width in (0, 1, 10, 40, 80, 160):
            line = status_line("/workspace/很长" * 10, "model" * 10, "local", "чат\n\x1b[31m",
                               "≈20%", {}, width)
            self.assertLessEqual(get_cwidth(line), width)
            self.assertNotIn("\n", line)
            self.assertNotIn("\x1b", line)
        self.assertEqual(shorten("e\u0301", 1), "e\u0301")
        line = status_line("/a", "model", "remote", "Временный", "—", {}, 120)
        for field in ("remote", "Временный", "контекст —", "подписка —/—"):
            self.assertIn(field, line)
        local = status_line("/a", "model", "local", "Временный", "—", {"remaining": 10}, 120)
        self.assertNotIn("подписка", local)

    def test_details_include_freshness_and_free_policy(self):
        text = limits_text({"limit": 1000, "used": 10, "remaining": 990, "fetched_at": 100,
                            "window_seconds": 86400})
        for field in ("990", "Бюджет подписки", "сутки (UTC)", "1970-01-01", "Сброс окна: —"):
            self.assertIn(field, text)

    def test_background_drops_previous_profile_and_does_not_send_draft(self):
        started, release, done = Event(), Event(), Event()
        client = Mock(mode="remote")
        def fetch(model):
            started.set()
            release.wait(2)
            return {"quotas": [{"scope": "old"}]}
        client.limits.side_effect = fetch
        client.context_info.return_value = {"input_tokens": 10}
        state = PromptStatus()
        state.update(client, ("old", "model"), "model", {"history": []}, done.set)
        self.assertTrue(started.wait(1))
        with state.lock:
            state.key, state.data, state.context = ("new", "model"), {}, {}
        release.set()
        self.assertTrue(done.wait(2))
        self.assertEqual(state.data, {})
        self.assertEqual(state.context, {})
        client.context_info.assert_called_once_with({"history": []})

    def test_local_has_no_limits_call_or_completion(self):
        from prompt_toolkit.document import Document
        from gemini_cli.client.completion import InputCompleter
        commands = InputCompleter(lambda: "/tmp", mode=lambda: "local")
        self.assertNotIn("/limits", [item.text for item in commands.get_completions(Document("/"), None)])
        client, done = Mock(mode="local"), Event()
        client.context_info.return_value = {}
        PromptStatus().update(client, "local", "model", {"history": []}, done.set)
        self.assertTrue(done.wait(2))
        client.limits.assert_not_called()

    def test_limits_usage_and_errors_never_send_chat(self):
        import importlib
        with tempfile.TemporaryDirectory() as home, unittest.mock.patch.dict(os.environ, {"HOME": home}):
            main = importlib.import_module("main")
        client = Mock(mode="remote")
        client.limits.return_value = {"kind": "subscription", "remaining": 10}
        with unittest.mock.patch.object(main, "PromptSession") as prompt, \
             unittest.mock.patch.object(main, "show_chat_menu", return_value=(None, True)), \
             unittest.mock.patch.object(main, "print_banner"), \
             unittest.mock.patch.object(main.PromptStatus, "update") as update, \
             unittest.mock.patch.object(main.console, "print") as printed:
            prompt.return_value.prompt.side_effect = ["/limits bad", "/limits refresh", "exit"]
            main.main(client)
        client.limits.assert_called_once_with("gemini-3.5-flash-lite", refresh=True)
        client.stream_chat.assert_not_called()
        payload = update.call_args.args[3]
        sent = main.build_stream_payload([{"role": "user", "content": "confirmed"}], None,
                                         "gemini-3.5-flash-lite", True)
        self.assertEqual(payload["supported_tools"], sent["supported_tools"])
        self.assertNotIn("message", payload)
        self.assertTrue(any("Использование: /limits" in str(getattr(call.args[0], "renderable", call.args[0]))
                            for call in printed.call_args_list))

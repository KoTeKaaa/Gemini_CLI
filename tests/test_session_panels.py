import importlib
import io
import unittest
from unittest.mock import Mock, patch
from rich.console import Console
from gemini_cli.client.input import result_panel


class SessionPanelTests(unittest.TestCase):
    def test_session_and_attachment_hints_use_named_panels(self):
        app = importlib.import_module("main")
        output = io.StringIO()
        backend = Mock(mode="local")
        with patch.object(app, "console", Console(file=output, width=160)), \
             patch.object(app, "show_chat_menu", return_value=(None, True)), \
             patch.object(app, "print_banner"), patch.object(app, "PromptSession") as prompt:
            prompt.return_value.prompt.side_effect = ["/session start", "/session", "/remove", "exit"]
            app.main(backend)
        text = output.getvalue()
        self.assertIn("Сессии", text)
        self.assertIn("/session start build", text)
        self.assertIn("Вложения", text)
        self.assertNotIn("Черновик", text)
        self.assertIn("╭", text)
        backend.stream_chat.assert_not_called()
        self.assertEqual(result_panel("Текст").title.plain, "Вложения")

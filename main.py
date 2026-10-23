import sys

if __name__ == '__main__' and sys.argv[1:] == ['--document-worker']:
    from gemini_cli.integrations.documents.worker import main as document_worker
    document_worker()
    raise SystemExit()

from gemini_cli.runtime.history import trim_history
from gemini_cli.client.file_attachment import attach_file
from gemini_cli.client.completion import InputCompleter
from gemini_cli.client.input import DraftInput, result_panel, safe_label
from prompt_toolkit.key_binding import merge_key_bindings
from gemini_cli.client.draft import Draft
from gemini_cli.client.chat_buffers import ChatBuffers, filter_chats
from gemini_cli.client.shell import launch_shell
from gemini_cli.client.work_input import WorkInput
from gemini_cli.client.work_view import WorkView
from gemini_cli.client.change_view import handle_change_command
from gemini_cli.client.quota_view import PromptStatus, status_line, limits_text, value
from prompt_toolkit.layout import ConditionalContainer, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.filters import is_done
from gemini_cli.protocol.images import encode_images
from gemini_cli.runtime.attachments import attachment_text, bound_image_history, restore_images, MARKER
import os
import json
import ipaddress
import tempfile
from contextlib import nullcontext
from uuid import uuid4
from pathlib import Path
from typing import Optional, Dict, List, Any
from urllib.parse import urlsplit

import requests
from gemini_cli.backends.base import Backend, StreamResult
from gemini_cli.runtime.compaction import should_auto_compact, completed_boundaries
from gemini_cli.runtime.turn import TurnState
from gemini_cli.backends.cancellation import open_stream, run_cancellable
from gemini_cli.client.settings import Settings, backend_identity
from gemini_cli.protocol.limits import TOOLS_HISTORY_THRESHOLD, TOOLS_WIRE_THRESHOLD
from gemini_cli.backends.remote import RemoteBackend, events_from_response as iter_stream_events
from prompt_toolkit import PromptSession
from prompt_toolkit.shortcuts import radiolist_dialog, yes_no_dialog
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit import HTML
from prompt_toolkit.styles import Style

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import logging
from datetime import datetime

from gemini_cli.client.tool_runner import execute_tool_calls as run_tool_calls
from gemini_cli.tools.local.command import execute_command
from gemini_cli.tools.local.symbols import project_map
from gemini_cli.tools.local.lsp_tools import python_lsp
from gemini_cli.tools.local.test_runner import run_tests
from gemini_cli.tools.local.affected import affected_tests
from gemini_cli.tools.local.git_tools import git_read
from gemini_cli.tools.local.git_commit import git_commit
from gemini_cli.tools.local.document import read_document
from gemini_cli.tools.local.files import read_files, write_files, read_file_lines
from gemini_cli.tools.local.search import find_files, search_text
from gemini_cli.tools.local.edit import replace_in_file
from gemini_cli.tools.local.changes import ChangeSet, ChangeHistory
from gemini_cli.tools.local.checkpoints import CheckpointStore
from gemini_cli.tools.definitions import CLIENT_NAMES
from gemini_cli.client.web_tools import ToolTurn
from gemini_cli.client.terminal import configure_output
from gemini_cli.tools.results import failure

configure_output()

LOG_FILE = os.path.join(os.path.expanduser("~"), ".gemini_cli", "gemini_cli.log")


def ensure_private_directory(path: str) -> None:
    os.makedirs(path, mode=0o700, exist_ok=True)
    if os.name == "posix":
        os.chmod(path, 0o700)


ensure_private_directory(os.path.dirname(LOG_FILE))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ]
)
logger = logging.getLogger("gemini_cli")



my_style = Style.from_dict({
    "": "ansibrightgreen",
    "status-line": "noinherit fg:#9ca3af bg:default",
    "status-rule": "noinherit fg:#4b5563 bg:default",
    "prompt": "noinherit fg:#60a5fa bg:default",
})

bindings = KeyBindings()
console = Console()


@bindings.add(Keys.Enter)
def _(event):
    event.current_buffer.validate_and_handle()


@bindings.add("c-j")
def _(event):
    event.current_buffer.newline()


HOME_DIR = os.path.expanduser("~")
APP_DIR = os.path.join(HOME_DIR, ".gemini_cli")
CONFIG_DIR = APP_DIR
SESSION_FILE = os.path.join(CONFIG_DIR, "session.json")
SERVER_FILE = os.path.join(CONFIG_DIR, "server_config.json")


def save_session(data: dict) -> None:
    directory = os.path.dirname(SESSION_FILE)
    ensure_private_directory(directory)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".session-", delete=False) as file:
            temporary_path = file.name
            json.dump(data, file, ensure_ascii=False, indent=4)
        os.replace(temporary_path, SESSION_FILE)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def normalize_server_url(value: str) -> str:
    url = value.strip() or "http://127.0.0.1:8000"
    if any(char.isspace() or ord(char) < 32 or char == "\\" for char in url):
        raise ValueError("Адрес сервера содержит недопустимые символы")
    if "://" not in url:
        url = f"//{url}"
        parsed = urlsplit(url)
        host = parsed.hostname
        if not host:
            raise ValueError("Укажите адрес сервера")
        scheme = "http" if is_loopback_host(host) else "https"
        url = f"{scheme}:{url}"

    parsed = urlsplit(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Укажите URL сервера без пути и учётных данных (HTTP или HTTPS)")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Некорректный порт сервера")
    if parsed.scheme == "http" and not is_loopback_host(parsed.hostname):
        raise ValueError("Для удалённого сервера требуется HTTPS")
    port = "" if parsed.port is not None else (":9443" if parsed.scheme == "https" else ":8000")
    return f"{parsed.scheme}://{parsed.netloc}{port}"


def is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def get_server_url() -> str:
    if os.path.exists(SERVER_FILE):
        try:
            with open(SERVER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                url = data.get("server_url", "http://127.0.0.1:8000")
                if url:
                    return normalize_server_url(url)
        except ValueError as e:
            console.print(f"[yellow]Сохранённый адрес сервера отклонён: {e}[/yellow]")
        except Exception as e:
            logger.exception(f"Необработанное исключение: {e}")

    console.print("[yellow]Конфигурация сервера не найдена.[/yellow]")
    while True:
        try:
            url = normalize_server_url(input("Введите URL или IP вашего сервера (например, https://YOUR_VPS_IP:9443): "))
            break
        except ValueError as e:
            console.print(f"[red]{e}[/red]")

    with open(SERVER_FILE, "w", encoding="utf-8") as f:
        json.dump({"server_url": url}, f, ensure_ascii=False, indent=4)

    return url


def confirm_content_scope(scope: str) -> bool:
    console.print(Text(scope))
    try:
        return input("Разрешить чтение и отправку содержимого модели? (y/n): ").strip().lower() == "y"
    except (EOFError, KeyboardInterrupt):
        return False


def confirm_file_read(readable: list[tuple[str, str]]) -> bool:
    table = Table(title="ИИ запрашивает чтение файлов")
    table.add_column("Запрошенный путь")
    table.add_column("Файл")
    for path, full_path in readable:
        table.add_row(Text(repr(path)), Text(full_path))
    console.print(table)
    try:
        return input("Разрешить чтение и отправку содержимого этих файлов модели? (y/n): ").strip().lower() == "y"
    except (EOFError, KeyboardInterrupt):
        return False


def confirm_replacement(path: str) -> bool:
    console.print(result_panel(f"Изменить файл: {safe_label(path)}", title="Запись файла"))
    try:
        return input("Применить замену? (y/n): ").strip().lower() == "y"
    except (EOFError, KeyboardInterrupt):
        return False


def handle_read_files(args: dict, current_dir: str) -> str:
    return read_files(args, current_dir, approve=confirm_file_read, logger=logger)


def confirm_file_write(files: list[dict]) -> bool:
    table = Table(title="🚨 Запрос на запись/изменение файлов", show_header=True, header_style="bold yellow")
    table.add_column("Путь (относительно рабочей папки)", style="cyan")
    table.add_column("Размер (символов)", style="magenta")

    for f in files:
        table.add_row(Text(safe_label(f.get("filepath", "unknown"))), str(len(f.get("content", ""))))

    console.print(table)

    console.print("")
    confirm = input("Разрешить создание/модификацию этих файлов? (y/n): ").strip().lower()

    if confirm != 'y':
        console.print("[bold red]❌ Операция заблокирована пользователем.[/bold red]\n")
        return False

    return True


def handle_write_files(args: dict, current_dir: str, *, changes=None, cancelled=lambda: False,
                       monitor=nullcontext) -> str:
    return write_files(args, current_dir, approve=confirm_file_write,
                       notify=lambda text: console.print(Text(safe_label(text))), logger=logger, changes=changes,
                       cancelled=cancelled, monitor=monitor)


def confirm_development_write(files: list[dict]) -> bool:
    from gemini_cli.client.paste import view_text
    view_text("\n\n".join(f['filepath'] + "\n" + f['content'] for f in files))
    return confirm_content_scope("Применить просмотренные изменения разработки?")


def confirm_development_action(text: str) -> bool:
    from gemini_cli.client.paste import view_text
    view_text(text)
    return confirm_content_scope("Выполнить просмотренное действие разработки?")


def confirm_command(command: str) -> bool:
    console.print(Panel(f"[bold white]{command}[/bold white]", title="⚙️ ИИ запрашивает выполнение команды терминала",
                        border_style="yellow"))

    confirm = input("Выполнить эту команду в вашей рабочей директории? (y/n): ").strip().lower()
    if confirm != 'y':
        console.print("[bold red]❌ Выполнение команды отменено пользователем.[/bold red]")
        return False

    return True


def handle_execute_command(args: dict, current_dir: str, *, state=None) -> str:
    return execute_command(
        args, current_dir, approve=confirm_command, notify=console.print, logger=logger,
        cancelled=state.cancelled.is_set if state else lambda: False,
        on_process=getattr(getattr(state, "view", None), "set_process", None),
        monitor=(state.view.monitor if state is not None and hasattr(state, "view")
                 else lambda: WorkInput(state)))


class GeminiAPIClient(RemoteBackend):
    def __init__(self, base_url: str):
        super().__init__(normalize_server_url(base_url),
                         profile_root=Path(SESSION_FILE).parent / "profiles",
                         legacy_session=Path(SESSION_FILE), credentials=prompt_credentials,
                         notify=lambda message: console.print(Text(message)))


def prompt_credentials():
    console.print("[bold cyan]Авторизируйтесь через email. Регистрация — по приглашению владельца.[/bold cyan]")
    try:
        return input("Email: ").strip(), PromptSession().prompt("Пароль: ", is_password=True)
    except (KeyboardInterrupt, EOFError):
        return None


def choose_setting(title, values):
    try:
        return radiolist_dialog(title=title, text="Esc — отмена", values=values).run()
    except (EOFError, KeyboardInterrupt):
        return None


def settings_controller():
    def server_origin(previous, force):
        if not force:
            return previous or get_server_url()
        try:
            return normalize_server_url(PromptSession().prompt("HTTPS-сервер: ", default=previous or ""))
        except (EOFError, KeyboardInterrupt):
            return None
    return Settings(Path(APP_DIR), remote_factory=GeminiAPIClient,
        choose_mode=lambda: choose_setting("Режим работы", [("local", "Local — личные ключи"),
                                                            ("remote", "Remote — подписка сервера")]),
        read_server=server_origin,
        choose_storage=lambda title: choose_setting(title, [("keyring", "Защищённое хранилище ОС"),
                                                            ("memory", "Только в памяти до закрытия")]),
        read_secret=lambda label: PromptSession().prompt(label, is_password=True),
        notify=lambda message: console.print(Text(message)))


def show_chat_menu(client: Backend, current_id=None, recent_ids=(), query="") -> Optional[tuple[Optional[str], bool]]:
    db_chats = client.get_chats()
    if db_chats is None:
        return None
    client.chat_titles = {chat["id"]: chat["title"] for chat in db_chats}
    while True:
        values = [("temporary", "Войти во временный чат"),
                  ("new", "+ Создать новую комнату диалога"),
                  ("search", "Поиск по названию…")]
        for chat in filter_chats(db_chats, query, current_id, recent_ids):
            marker = " · текущий" if chat["is_current"] else ""
            values.append((chat["id"], f"Чат: {chat['title']} ({chat['created_at'][:10]}){marker}"))
        result = radiolist_dialog(title="Выбор комнаты",
            text=f"Поиск: {query}" if query else "Выберите чат для работы или создайте новый:",
            values=values).run()
        if result == "search":
            query = input("Название чата (пусто — все): ").strip()
            continue
        if result is None:
            return None
        if result == "temporary":
            return None, True
        if result == "new":
            title = input("Введите название нового чата: ").strip() or "Новый диалог"
            new_chat = client.create_chat(title)
            if new_chat:
                client.chat_titles[new_chat["id"]] = new_chat.get("title", title)
                return new_chat["id"], False
            console.print(result_panel("Не удалось создать чат.", title="Чаты", error=True))
            return None
        return result, False


def context_wire_history(history, summary=None, *, strict=True):
    """Retain the archive, transmitting only its represented boundary and tail."""
    if summary and summary.get("boundary_id"):
        index = next((i for i, row in enumerate(history)
                      if row.get("id") == summary["boundary_id"]), None)
        if index is None:
            if strict:
                raise ValueError("Граница сводки отсутствует в контексте. Сжатие нужно повторить.")
        else:
            history = history[index:]
    return history


def inspect_context(client, payload):
    state = TurnState()
    state.view = WorkView(console, state)
    try:
        with state.view.monitor():
            return run_cancellable(lambda: client.context_info(payload), state)
    finally:
        state.finish()


def context_payload(history, chat_id, model, summary=None):
    history = context_wire_history(history, summary, strict=chat_id is None)
    if chat_id is not None:
        history = history[-1000:]  # Stored history remains authoritative and complete.
    elif len(history) > 10000:
        raise ValueError("Сжатие ограничено 10000 событиями; начните новый чат.")
    payload = {"history": history, "chat_id": chat_id, "model_name": model}
    if summary:
        payload.update(summary=summary.get("summary"),
                       summary_boundary=summary.get("boundary_id"))
    return payload


def status_context_payload(history, chat_id, model, summary=None, *, mcp=None, skill=None):
    payload = context_payload(history, chat_id, model, summary)
    # Use the actual next-turn policy, including history/wire thresholds,
    # without transmitting a hypothetical message or the unsent draft.
    preview = build_stream_payload([*history, {"role": "user", "content": ""}],
                                   chat_id, model, chat_id is None, summary=summary, mcp=mcp, skill=skill)
    payload["supported_tools"] = preview["supported_tools"]
    if preview.get("mcp_tools"):
        payload["mcp_tools"] = preview["mcp_tools"]
    if preview.get('skill_context'):
        payload['skill_context'] = preview['skill_context']
    return payload


def compact_context(client, history, chat_id, model, summary=None, *, blocked_fingerprint=None):
    """The worker returns a candidate; cancellation rejects late UI results."""
    state = TurnState()
    state.view = WorkView(console, state)
    try:
        payload = context_payload(history, chat_id, model, summary)
        if blocked_fingerprint:
            payload["blocked_fingerprint"] = blocked_fingerprint
        with state.view.monitor():
            result = run_cancellable(lambda: client.compact_chat(
                payload,
                cancelled=state.cancelled.is_set), state)
        if state.cancelled.is_set():
            raise InterruptedError("Сжатие отменено")
        if not isinstance(result, dict):
            raise ValueError("Backend не вернул результат сжатия")
        if isinstance(client, RemoteBackend) and chat_id and result.get("reason") == "ready":
            # WorkInput is already detached. A committed RPC cannot be cancelled.
            console.print(result_panel("Сохраняю сводку. Дождитесь завершения.", title="Контекст"))
            client.apply_compaction(payload, result)
        return result
    except InterruptedError:
        return {"reason": "cancelled", "summary": None, "boundary_id": None}
    finally:
        state.finish()


def failed_prompt_after(history, boundary_id):
    index = next((i for i, row in enumerate(history)
                  if (row.get("id") or row.get("event_id")) == boundary_id), None)
    if index is None:
        return None
    turns = []
    for row in history[index + 1:]:
        if row.get("role") == "user":
            turns.append([])
        if turns:
            turns[-1].append(row)
    for turn in reversed(turns):
        if any(row.get("status") in {"failed", "cancelled"} for row in turn):
            content = turn[0].get("content")
            if isinstance(content, str):
                text = content.rsplit(MARKER, 1)[0]
                if text.strip():
                    return text
    return None


def fork_context(client, chat_id, title=""):
    history = client.get_history(chat_id)
    if not isinstance(history, list):
        raise ValueError("История исходного чата недоступна")
    boundaries = completed_boundaries(history)
    if not boundaries:
        raise ValueError("Нет завершённых ходов с достоверными идентификаторами для форка")
    values = [(index, f"{index + 1}. {safe_label(row.get('content', ''))[:90]}")
              for index, row in enumerate(boundaries)]
    choice = radiolist_dialog(title="Граница форка", text="Включить историю до выбранного завершённого хода:",
                              values=values, default=len(values) - 1).run()
    if choice is None:
        return None
    title = title.strip() or input("Название нового чата: ").strip()
    if not title:
        return None
    selected = boundaries[choice]
    result = client.fork_chat(chat_id, title, selected.get("id") or selected.get("event_id"))
    if not isinstance(result, dict) or not result.get("id"):
        raise ValueError("Не удалось создать форк чата")
    failed = failed_prompt_after(history, selected.get("id") or selected.get("event_id"))
    if failed and yes_no_dialog(title="Восстановление запроса",
            text="Вернуть текст последнего неудачного или отменённого запроса в черновик? "
                 "Отправка останется ручной; вложения нужно прикрепить заново.").run():
        result = {**result, "_restore_prompt": failed}
    return result


def show_model_selection_menu(current_model: str) -> str:
    available_models = [
        ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite"),
        ("gemini-3.8-flash", "Gemini 3.8 Flash"),
        ("gemini-3.7-flash", "Gemini 3.7 Flash"),
        ("gemini-3.6-flash", "Gemini 3.6 Flash"),
        ("gemini-3.5-flash", "Gemini 3.5 Flash"),
    ]

    values = []
    for model_id, label in available_models:
        if model_id == current_model:
            values.append((model_id, f"{label} (Активна)"))
        else:
            values.append((model_id, label))

    result = radiolist_dialog(
        title="Выбор ИИ модели",
        text="Выберите модель для текущей сессии (Управление стрелочками, Enter — подтвердить):",
        values=values,
    ).run()

    if result is None:
        return current_model

    console.print(f"[green]Успешно переключено на модель: {result}[/green]\n")
    logger.info(f"Модель изменена на: {result}")
    return result



def build_stream_payload(history: List[Dict[str, Any]], chat_id: Optional[str],
                         model_name: str, is_temporary: bool, turn: ToolTurn | None = None,
                         *, end_tool_turn: bool = False, summary=None, mcp=None, skill=None) -> Dict[str, Any]:
    history = context_wire_history(history, summary, strict=is_temporary)
    if not is_temporary and len(history) > 1000:
        if history[-1].get("role") == "tool":
            start = next((i for i in range(len(history) - 1, -1, -1)
                          if history[i].get("role") == "user"), 0)
            if len(history) - start > 1000:
                raise ValueError("Текущий ход превышает 1000 событий; продолжение остановлено.")
        history = history[-1000:]
    if not history or len(history) > 1000:
        raise ValueError("Контекст пуст или превышает 1000 событий. Используйте /compact или новый чат.")
    continuing = bool(history and history[-1].get("role") == "tool")
    payload: Dict[str, Any] = {
        "message": "" if continuing else history[-1]["content"],
        "chat_id": chat_id,
        "model_name": model_name,
        "continue_after_tool": continuing,
        "supported_tools": [name for name in CLIENT_NAMES
                            if name != "web_search" or turn is None or turn.search_available],
    }
    if continuing:
        payload["history"] = history
        if end_tool_turn:
            payload["end_tool_turn"] = True
            payload["supported_tools"] = []
    elif is_temporary or any(row.get("images") for row in history):
        payload["history"] = history[:-1]
    if not continuing and history[-1].get("images"):
        payload["images"] = history[-1]["images"]
    if summary:
        payload.update(summary=summary.get("summary"), summary_boundary=summary.get("boundary_id"))
    if skill is not None:
        from gemini_cli.protocol.skills import validate_skill
        validate_skill(skill)
        payload['skill_context'] = dict(skill)
    text_payload = {key: value for key, value in payload.items() if key != "images"}
    if "history" in text_payload:
        text_payload["history"] = [{key: value for key, value in row.items() if key != "images"}
                                   for row in text_payload["history"]]
    if len(history) > TOOLS_HISTORY_THRESHOLD or len(json.dumps(text_payload).encode()) > TOOLS_WIRE_THRESHOLD:
        payload["supported_tools"] = []
    if mcp is not None and payload["supported_tools"]:
        declarations = mcp.declarations()
        if declarations:
            payload["mcp_tools"] = declarations
            payload["supported_tools"].extend(row["name"] for row in declarations)
    return payload


def execute_tool_calls(tool_calls: List[Dict[str, Any]], history: List[Dict[str, Any]],
                       current_dir: str, *, turn: ToolTurn | None = None, api_client: Backend | None = None, state=None, mcp=None) -> None:
    changes = getattr(state, "changes", None)
    if changes is None:
        changes = ChangeSet(current_dir, getattr(state, "turn_id", ""),
                            store=CheckpointStore(Path(CONFIG_DIR) / "checkpoints"))
        if state is not None:
            state.changes = changes
    cancelled = state.cancelled.is_set if state else lambda: False
    monitor = (lambda: WorkInput(state)) if state else nullcontext
    handlers = {
        "read_document": lambda args, cwd: json.dumps(read_document(
            args, cwd, approve=confirm_content_scope, cancelled=cancelled, monitor=monitor), ensure_ascii=False),
        "git_commit": lambda args, cwd: json.dumps(git_commit(
            args, cwd, approve=confirm_development_action, cancelled=cancelled, monitor=monitor), ensure_ascii=False),
        "git_read": lambda args, cwd: json.dumps(git_read(
            args, cwd, approve=confirm_content_scope, cancelled=cancelled, monitor=monitor), ensure_ascii=False),
        "affected_tests": lambda args, cwd: json.dumps(affected_tests(
            args, cwd, approve=confirm_content_scope), ensure_ascii=False),
        "run_tests": lambda args, cwd: json.dumps(run_tests(
            args, cwd, approve=confirm_content_scope, cancelled=cancelled, monitor=monitor,
            on_process=getattr(getattr(state, "view", None), "set_process", None)), ensure_ascii=False),
        "python_lsp": lambda args, cwd: json.dumps(python_lsp(
            args, cwd, approve=confirm_content_scope, cancelled=cancelled, changes=changes,
            confirm_write=confirm_development_write, monitor=monitor), ensure_ascii=False),
        "python_symbols": lambda args, cwd: json.dumps(project_map(
            cwd, approve=confirm_content_scope, query=args.get("query", "")), ensure_ascii=False),
        "read_local_files": handle_read_files,
        "write_local_files": lambda args, cwd: handle_write_files(args, cwd, changes=changes,
                                                                 cancelled=cancelled, monitor=monitor),
        "execute_command": (handle_execute_command if state is None else
                            lambda args, cwd: handle_execute_command(args, cwd, state=state)),
        "find_files": lambda args, cwd: json.dumps(find_files(args, cwd), ensure_ascii=False),
        "replace_in_file": lambda args, cwd: json.dumps(replace_in_file(
            args, cwd, approve=confirm_content_scope,
            confirm_diff=lambda _: confirm_replacement(args.get("filepath", "")),
            changes=changes, cancelled=cancelled, monitor=monitor), ensure_ascii=False),
        "read_file_lines": lambda args, cwd: json.dumps(read_file_lines(args, cwd, approve=confirm_content_scope),
                                                         ensure_ascii=False),
        "search_text": lambda args, cwd: json.dumps(search_text(args, cwd, approve=confirm_content_scope),
                                                     ensure_ascii=False),
    }
    if turn is not None and api_client is not None:
        def web_handler(kind, args):
            operation = lambda: (turn.search(args, api_client.web_tool) if kind == "search"
                                 else turn.read(args, api_client.web_tool))
            try:
                if state is None:
                    result = operation()
                else:
                    with state.view.monitor() if hasattr(state, "view") else WorkInput(state):
                        result = run_cancellable(operation, state)
            except InterruptedError:
                return json.dumps(failure("cancelled", "Ход отменён; результат веб-вызова не принят"))
            turn.report(kind, json.loads(result), lambda text: console.print(Text(text)))
            return result
        handlers["web_search"] = lambda args, _cwd: web_handler("search", args)
        handlers["read_url"] = lambda args, _cwd: web_handler("read", args)
    if mcp is not None:
        from gemini_cli.client.mcp_commands import approve_call
        def approve(server, original, values):
            return approve_call(console, server, original, values)
        def invoke(operation):
            with (state.view.monitor() if state is not None and hasattr(state, "view") else monitor()):
                return operation()
        def mcp_handler(name, args):
            return mcp.call(name, args, approve=approve, cancelled=cancelled, invoke=invoke)
        for declaration in mcp.declarations():
            name = declaration["name"]
            handlers[name] = lambda args, _cwd, name=name: mcp_handler(name, args)
        from gemini_cli.integrations.github_pr import github_pr
        handlers['github_pr'] = lambda args, cwd: json.dumps(github_pr(
            args, cwd, manager=mcp, approve=approve, cancelled=cancelled,
            invoke=invoke, monitor=monitor), ensure_ascii=False)
    run_tool_calls(tool_calls, history, current_dir, handlers=handlers, logger=logger, state=state)



def display_stream_response(response, has_pending_tool: bool, state=None):
    full_response = ""
    tool_calls_received = []
    error_content = None
    use_preview = console.is_terminal and not console.is_dumb_terminal
    view = getattr(state, "view", None) or WorkView(console, state)
    view.update_text("")
    with view.monitor():
        started_text = False
        line_ended = False
        try:
            for event in iter_stream_events(response):
                if state is not None and not state.accepts(event):
                    continue
                event_type = event.get("type")
                if event_type == "text":
                    fragment = event.get("content", "")
                    if fragment:
                        full_response += fragment
                        started_text = True
                        if use_preview:
                            view.update_text(full_response)
                        else:
                            sys.stdout.write(fragment)
                            sys.stdout.flush()
                        line_ended = fragment.endswith("\n")
                elif event_type == "tool_call":
                    tool_calls_received.append(event)
                elif event_type == "error":
                    error_content = event.get("content")
                    break
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
            if not use_preview and started_text and not line_ended:
                sys.stdout.write("\n")
                sys.stdout.flush()
    if state is not None and state.cancelled.is_set():
        return "", []
    if error_content is not None:
        console.print(f"[bold red]Ошибка:[/] {error_content}")
        return "", []
    if use_preview and full_response and not tool_calls_received:
        console.print(Markdown(full_response))
    return full_response, tool_calls_received


def print_banner(model: str, chat_mode: str, current_dir: str):
    GEMINI_BLUE = "#4285F4"
    GEMINI_TEAL = "#00BCD4"

    logo = """[#4285F4]     ██████╗ [/#4285F4][#00BCD4] ███████╗[/#00BCD4][#4285F4]███╗   ███╗[/#4285F4][#00BCD4]██╗[/#00BCD4][#4285F4]███╗   ██╗[/#4285F4][#00BCD4]██╗[/#00BCD4]
[#4285F4]    ██╔════╝ [/#4285F4][#00BCD4] ██╔════╝[/#00BCD4][#4285F4]████╗ ████║[/#4285F4][#00BCD4]██║[/#00BCD4][#4285F4]████╗  ██║[/#4285F4][#00BCD4]██║[/#00BCD4]
[#4285F4]    ██║  ███╗[/#4285F4][#00BCD4] █████╗  [/#00BCD4][#4285F4]██╔████╔██║[/#4285F4][#00BCD4]██║[/#00BCD4][#4285F4]██╔██╗ ██║[/#4285F4][#00BCD4]██║[/#00BCD4]
[#4285F4]    ██║   ██║[/#4285F4][#00BCD4] ██╔══╝  [/#00BCD4][#4285F4]██║╚██╔╝██║[/#4285F4][#00BCD4]██║[/#00BCD4][#4285F4]██║╚██╗██║[/#4285F4][#00BCD4]██║[/#00BCD4]
[#4285F4]    ╚██████╔╝[/#4285F4][#00BCD4] ███████╗[/#00BCD4][#4285F4]██║ ╚═╝ ██║[/#4285F4][#00BCD4]██║[/#00BCD4][#4285F4]██║ ╚████║[/#4285F4][#00BCD4]██║[/#00BCD4]
[#4285F4]     ╚═════╝ [/#4285F4][#00BCD4] ╚══════╝[/#00BCD4][#4285F4]╚═╝     ╚═╝[/#4285F4][#00BCD4]╚═╝[/#00BCD4][#4285F4]╚═╝  ╚═══╝[/#4285F4][#00BCD4]╚═╝[/#00BCD4]"""

    console.print(logo)

    info_table = Table.grid(padding=(0, 2))
    info_table.add_column(style="dim")
    info_table.add_column(style="bold white")

    info_table.add_row("⚡ Модель",    f"[#4285F4]{model}[/#4285F4]")
    info_table.add_row("💬 Режим",     f"[#00BCD4]{chat_mode}[/#00BCD4]")
    info_table.add_row("📁 Workspace", f"[white]{current_dir}[/white]")
    info_table.add_row("❓ Справка",   "[dim]/help[/dim]")

    console.print(Panel(
        info_table,
        border_style="#4285F4",
        padding=(0, 1),
    ))
    console.print()

def main(backend: Backend | None = None):
    api_client = backend
    settings = settings_controller() if backend is None else None
    if api_client is None:
        api_client = settings.configure()
        if api_client is None:
            return

    current_model = "gemini-3.5-flash-lite"
    selected_chat = show_chat_menu(api_client)
    if selected_chat is None:
        if settings:
            settings.close()
        return
    chat_id, is_temporary = selected_chat
    current_dir = os.getcwd()
    chat_mode = "ВРЕМЕННЫЙ" if is_temporary else "ПОСТОЯННЫЙ"
    print_banner(current_model, chat_mode, current_dir)

    draft = Draft()
    draft_input = DraftInput(draft)
    file_changes = {}
    mcp_managers = {}
    from gemini_cli.client.skill_commands import Selection
    from gemini_cli.client.skill_resources import choices as skill_resource_choices
    skill_selection = Selection(Path(CONFIG_DIR) / 'skills.json')
    def active_skill():
        return skill_selection.bind((backend_identity(api_client), chat_id, os.path.realpath(current_dir)))
    def active_mcp():
        from gemini_cli.integrations.mcp.manager import Manager
        identity = backend_identity(api_client)
        if identity not in mcp_managers:
            mcp_managers[identity] = Manager(Path(CONFIG_DIR), identity)
        return mcp_managers[identity]
    def active_changes():
        return file_changes.get((backend_identity(api_client), chat_id, os.path.realpath(current_dir)))
    def mcp_choices():
        try:
            return tuple(active_mcp().connections)
        except (ValueError, OSError):
            return ()
    completer = InputCompleter(lambda: current_dir, mode=lambda: api_client.mode,
                              mcp_choices=mcp_choices,
                              skill_choices=lambda: active_skill().choices(),
                              skill_resources=lambda action, fragment: skill_resource_choices(active_skill(), action, fragment),
                              change_choices=lambda: list(active_changes().active_files()) if active_changes() else (),
                              attachment_choices=lambda: [
        (number, draft_input.describe(number, item)) for number, item in draft.items()])
    session = PromptSession(completer=completer, complete_while_typing=True,
                            key_bindings=merge_key_bindings([bindings, draft_input.bindings]),
                            style=my_style, bottom_toolbar=draft_input.status)

    temporary_history: List[Dict[str, str]] = []
    buffers, states, summary = ChatBuffers(), {}, None
    auto_attempts = {}
    prompt_status = PromptStatus()
    def input_status():
        info = prompt_status.context
        tokens, limit = info.get("input_tokens"), info.get("input_token_limit")
        text = session.default_buffer.text
        # Only a local estimate of the unsent draft; no clipboard bytes or
        # unconfirmed text is transmitted by the status display.
        if draft.images or tokens is None:
            context = "—"
        else:
            try:
                draft_text = draft.message(text)
                tokens += (len(draft_text) + 3) // 4
                context = "≈" + (f"{100 * tokens / limit:.0f}%" if limit else value(tokens) + "/—")
            except ValueError:
                context = "—"
        titles = getattr(api_client, "chat_titles", {})
        title = "Временный" if is_temporary else (titles.get(chat_id, "Чат") if isinstance(titles, dict) else "Чат")
        width = session.app.output.get_size().columns
        selected = active_skill().skill
        skill_label = ('skill ' + selected.name[:max(1, min(24, width // 3))] + ' · ') if selected else ''
        line = skill_label + status_line(current_dir, current_model, api_client.mode, title, context,
                                        prompt_status.data, max(0, width - len(skill_label)))
        return [("class:status-rule", "─" * max(0, width) + "\n"),
                ("class:status-line", line)]
    session.layout.container.children.insert(0, ConditionalContainer(
        Window(FormattedTextControl(input_status), height=2), filter=~is_done))
    buffers.visit(backend_identity(api_client), chat_id)
    if not is_temporary:
        try:
            loaded = api_client.get_history(chat_id)
            if isinstance(loaded, list):
                temporary_history = loaded
        except Exception:
            console.print(result_panel("Не удалось загрузить историю. Backend продолжит постоянный чат; локальный просмотр пока недоступен.", title="Чаты", error=True))

    def remember():
        buffers.save(backend_identity(api_client), chat_id, temporary_history, draft, summary)

    def load_buffer(client, target_id):
        scope = backend_identity(client)
        saved = buffers.restore(scope, target_id)
        if saved is None:
            history = [] if target_id is None else client.get_history(target_id)
            if not isinstance(history, list):
                raise ValueError("История чата недоступна; переключение отменено")
            saved = {"history": history, "draft": Draft(), "summary": None}
            buffers.visit(scope, target_id)
        return saved

    def apply_buffer(saved):
        nonlocal temporary_history, draft, summary
        temporary_history, draft, summary = saved["history"], saved["draft"], saved["summary"]
        draft_input.draft = draft
    def apply_summary(result):
        nonlocal summary, temporary_history
        text = result.get("summary")
        if (result.get("reason") != "ready" or not isinstance(text, str)
                or not text.strip() or len(text) > 8192 or not result.get("boundary_id")):
            return False
        summary = result
        if not is_temporary:
            try:
                stored = api_client.get_history(chat_id)
                if isinstance(stored, list):
                    temporary_history = restore_images(stored, temporary_history)
            except Exception:
                pass  # Persisted summary is authoritative; keep the full live archive.
        remember()
        return True

    console.print(Text(f"Backend: {api_client.mode}"))

    while True:
        try:
            # Reauthentication belongs to the UI thread, outside raw work input.
            if isinstance(api_client, RemoteBackend) and not api_client.token:
                if not api_client.login():
                    break
            draft_input.take_notice()
            try:
                status_payload = status_context_payload(temporary_history, chat_id, current_model, summary,
                                                        mcp=active_mcp(), skill=active_skill().payload())
                from hashlib import sha256
                status_key = (backend_identity(api_client), current_model, chat_id,
                              sha256(json.dumps(status_payload, sort_keys=True).encode()).digest())
                prompt_status.update(api_client, status_key, current_model, status_payload, session.app.invalidate)
            except ValueError:
                prompt_status.context = {}
            user_input = session.prompt(HTML('<style class="prompt"> › </style>'), default=draft.text)

            if not user_input.strip():
                draft.text = ""
                draft.retry_pending = False
                continue

            first_line = user_input.strip().split("\n")[0]
            if draft.retry_pending and (first_line.startswith("/") or user_input.startswith("@")):
                # The user replaced the composer with a local action. Do not
                # restore the old failed request after the action completes.
                draft.text = ""
                draft.retry_pending = False
            if first_line.lower() in ["выход", "exit", "quit", "q", "й"]:
                console.print("[bold red]Рад был помочь![/bold red]")
                break

            if user_input.startswith('@'):
                try:
                    number = attach_file(draft, user_input.strip(), current_dir,
                                snapshots=completer.snapshots, approve=lambda _: True)
                    result = ('Прикрепление отменено.' if number is None else
                              'Добавлено ' + draft_input.describe(number, draft.item(number)) + '. Отправка — Enter.')
                except (ValueError, OSError) as error:
                    console.print(result_panel(str(error), title="Файл не добавлен", error=True))
                    continue
                console.print(result_panel(result, title="Вложения"))
                continue

            if draft_input.command(user_input.strip()):
                console.print(result_panel(draft_input.take_notice(),
                                           title="Вложения"))
                continue

            if first_line.startswith("/help"):
                table = Table(title="Доступные команды Gemini-CLI", show_header=True, header_style="bold magenta")
                table.add_column("Команда", style="cyan")
                table.add_column("Описание", style="white")

                table.add_row("/show 1, /edit 1", "Просмотр вложения #1 (изображение — в приложении ОС); изменение текста")
                if api_client.mode == "remote":
                    table.add_row("/limits [refresh]", "Бюджет подписки сервиса; пример: /limits refresh")
                table.add_row("Ctrl+V, /paste", "Прикрепить скриншот из буфера")
                table.add_row("@file", "Добавить файл целиком в черновик; отправка отдельным сообщением")
                table.add_row("@file:1-20", "Прикрепить строки с 1 по 20 включительно (без скобок)")
                table.add_row("@file:7", "Прикрепить только строку 7")
                table.add_row("/attachments", "Общий список файлов, изображений и вставок с номерами")
                table.add_row("/remove 1", "Удалить вложение #1 любого типа; номера остальных сохраняются")
                table.add_row("/show, /edit", "Без номера: выбрать единственное вложение или показать список")
                table.add_row("/remove", "Показать номера для выбора; без номера ничего не удаляет")
                table.add_row("/help", "Показать эту справку")
                table.add_row("/diff [путь]", "Список правок чата или diff файла; пример: /diff src/file.py")
                table.add_row("/undo [путь]", "Список правок или откат файла; пример: /undo src/file.py")
                table.add_row("/model", "Сменить ИИ модель")
                table.add_row("/mcp", "Подключения MCP; /mcp help — гайд для первого подключения")
                table.add_row('/skill', 'Навыки; /skill help — гайд по созданию и использованию')
                table.add_row('/dev help', 'Код, LSP, тесты, Git и PR; настройка и примеры')
                table.add_row("/settings", "Local/Remote, сервер и личные ключи")
                table.add_row("/chat", "Сменить или создать комнату диалога")
                table.add_row("/clear", "Очистить временный чат и его черновик; постоянный чат сохраняется")
                table.add_row("/compact", "Сжать завершённые ходы в контекст; Esc отменяет")
                table.add_row("/fork Новый вариант", "Создать отдельный чат до выбранного завершённого хода")
                table.add_row("/delete", "Удалить текущий постоянный чат")
                table.add_row("/cd {путь}", "Изменить текущую рабочую папку для Gemini")
                table.add_row("/term", "Открыть оболочку; exit-to-cli возвращает в этот чат")
                table.add_row("Esc / F2", "Во время ответа: отменить ход / показать или скрыть вывод инструментов")
                table.add_row("exit, quit, q", "Выход из приложения")

                console.print(Panel(table, title="[bold green]Справка[/bold green]", expand=False))
                continue

            if handle_change_command(user_input, active_changes(), console):
                continue

            if first_line.split()[0] == "/term":
                if user_input.strip() != "/term":
                    console.print(result_panel("Использование: /term (без аргументов).", title="Терминал", error=True))
                    continue
                try:
                    directory = launch_shell(current_dir, announce=lambda message: console.print(result_panel(message, title="Терминал")))
                    if directory is not None:
                        current_dir = directory
                        console.print(result_panel(f"Текущая папка сменена на: {current_dir}", title="Терминал"))
                except (ValueError, OSError) as exc:
                    console.print(result_panel(str(exc), title="Терминал", error=True))
                continue

            if first_line.split()[0] == "/limits" and api_client.mode == "remote":
                if user_input.strip() not in {"/limits", "/limits refresh"}:
                    console.print(result_panel("Использование: /limits или /limits refresh. Пример: /limits refresh.",
                                               title="Подписка", error=True))
                    continue
                state = TurnState()
                state.view = WorkView(console, state)
                try:
                    with state.view.monitor():
                        data = run_cancellable(lambda: api_client.limits(current_model,
                                               refresh=user_input.strip().endswith(" refresh")), state)
                    prompt_status.data = data
                    console.print(result_panel(limits_text(data), title="Подписка"))
                except Exception:
                    console.print(result_panel("Бюджет подписки недоступен. Пример: /limits refresh.",
                                               title="Подписка", error=True))
                finally:
                    state.finish()
                continue

            if first_line.strip().split(" ", 1)[0] == '/dev':
                from gemini_cli.client.development_help import command as development_command
                from gemini_cli.client.paste import view_text
                development_command(user_input, console=console, viewer=view_text)
                continue

            if first_line.strip().split(" ", 1)[0] == '/skill':
                from gemini_cli.client.skill_commands import command as skill_command
                from gemini_cli.client.skill_resources import run as run_skill
                from gemini_cli.client.paste import view_text
                def run_selected_skill(selection, relative):
                    state = TurnState()
                    view = WorkView(console, state)
                    view.spinner.text = 'Выполнение скрипта навыка...'
                    def approve(label):
                        console.print(Text(label + '\nВнешние действия скрипта не откатываются через /undo.'))
                        try:
                            return PromptSession(input=session.input, output=session.output).prompt(
                                'Запустить просмотренный скрипт? (y/n): ').strip().lower() == 'y'
                        except (EOFError, KeyboardInterrupt):
                            return False
                    return run_skill(selection, relative, current_dir, approve=approve,
                                     cancelled=state.cancelled.is_set, on_process=view.set_process,
                                     monitor=view.monitor, notify=lambda _: None)
                skill_command(first_line, active_skill(), console=console, viewer=view_text,
                              run_script=run_selected_skill)
                continue
            if first_line.strip().split(" ", 1)[0] == "/mcp":
                from gemini_cli.client.mcp_commands import command, prompt_secret
                try:
                    command(first_line, manager_factory=active_mcp, console=console,
                            read_secret=lambda label: prompt_secret(label, input=session.input, output=session.output))
                except ValueError:
                    console.print(result_panel("MCP: неверный приватный mcp.json", title="MCP", error=True))
                continue
            if first_line.strip() == "/settings":
                if settings is None:
                    console.print("Настройки недоступны для внедрённого backend")
                    continue
                replacement = settings.configure(force=True)
                if replacement is not None:
                    remember()
                    states[backend_identity(api_client)] = (chat_id, is_temporary, current_model)
                    target_id, target_temporary, target_model = states.get(
                        backend_identity(replacement), (None, True, current_model))
                    try:
                        saved = load_buffer(replacement, target_id)
                    except ValueError as error:
                        console.print(result_panel(str(error), title="Чаты", error=True))
                        continue
                    api_client, chat_id, is_temporary, current_model = replacement, target_id, target_temporary, target_model
                    apply_buffer(saved)
                    console.print(result_panel(f"Backend: {api_client.mode}; черновик и контекст восстановлены", title="Чаты"))
                continue

            if first_line.startswith("/delete"):
                if is_temporary:
                    console.print("[yellow]Временный чат удалить нельзя.[/yellow]")
                    continue
                confirm = input(f"Удалить текущий чат? Это необратимо. (y/n): ").strip().lower()
                if confirm == "y":
                    if api_client.delete_chat(chat_id):
                        logger.info(f"Чат {chat_id} удалён")
                        console.print("[green]Чат удалён. Переключаемся во временный режим.[/green]")
                        chat_id = None
                        is_temporary = True
                        apply_buffer(load_buffer(api_client, None))
                    else:
                        console.print("[red]Не удалось удалить чат.[/red]")
                continue


            if first_line.startswith("/model"):
                current_model = show_model_selection_menu(current_model)
                continue

            if first_line.split()[0] == "/compact":
                if user_input.strip() != "/compact":
                    console.print(result_panel("Использование: /compact (без аргументов).", title="Контекст", error=True))
                    continue
                try:
                    result = compact_context(api_client, temporary_history, chat_id, current_model, summary)
                    if apply_summary(result):
                        auto_attempts.pop((backend_identity(api_client), chat_id), None)
                        message = "Сводка обновлена. Полная история сохранена."
                    else:
                        message = {"cancelled": "Сжатие отменено. Контекст сохранён.",
                                   "no_completed_boundary": "Недостаточно завершённых ходов для сжатия."}.get(
                                       result.get("reason"), "Сжатие не выполнено. Контекст сохранён.")
                    console.print(result_panel(message, title="Контекст", error=not bool(result.get("summary"))))
                except Exception:
                    console.print(result_panel("Не удалось сжать контекст. История сохранена.", title="Контекст", error=True))
                continue

            if first_line.split()[0] == "/fork":
                if is_temporary:
                    console.print(result_panel("/fork доступна только в постоянном чате.", title="Форк", error=True))
                    continue
                try:
                    fork = fork_context(api_client, chat_id, first_line.partition(" ")[2])
                    if fork:
                        remember()
                        saved = load_buffer(api_client, fork["id"])
                        chat_id, is_temporary = fork["id"], False
                        apply_buffer(saved)
                        if fork.get("_restore_prompt"):
                            draft.text = (draft.text + "\n\n" if draft.text else "") + fork["_restore_prompt"]
                            remember()
                        console.print(result_panel("Форк создан; история скопирована без повторного выполнения действий.", title="Форк"))
                except Exception:
                    console.print(result_panel("Не удалось открыть форк. Исходный чат и черновик сохранены.", title="Форк", error=True))
                continue

            if first_line.split()[0] == "/clear":
                if first_line.strip() != "/clear" or not is_temporary:
                    console.print(result_panel("/clear доступна без аргументов только во временном чате.", title="Контекст", error=True))
                else:
                    apply_buffer(buffers.clear_temporary(backend_identity(api_client)))
                    active_skill().clear()
                    console.print(result_panel("Временный контекст и черновик очищены.", title="Контекст"))
                continue

            if first_line.startswith("/chat"):
                selected_chat = show_chat_menu(api_client, current_id=chat_id,
                    recent_ids=buffers.recent_ids(backend_identity(api_client)))
                if selected_chat is None:
                    continue
                new_chat_id, new_is_temporary = selected_chat
                if new_chat_id != chat_id or new_is_temporary != is_temporary:
                    remember()
                    try:
                        saved = load_buffer(api_client, new_chat_id)
                    except ValueError as error:
                        console.print(result_panel(str(error), title="Чаты", error=True))
                        continue
                    chat_id, is_temporary = new_chat_id, new_is_temporary
                    apply_buffer(saved)
                    chat_mode = "ВРЕМЕННЫЙ" if is_temporary else "ПОСТОЯННЫЙ"
                    console.print(f"[yellow]Переключились на чат. Режим: {chat_mode}[/yellow]\n")
                continue

            if first_line.startswith("/cd"):
                parts = user_input.strip().split(" ", 1)
                if len(parts) != 2:
                    console.print(f"[yellow]Текущая папка: {current_dir}[/yellow]")
                    continue

                target_path = os.path.abspath(os.path.join(current_dir, parts[1]))

                if not os.path.isdir(target_path):
                    if os.path.lexists(target_path):
                        console.print(f"[red]Путь '{target_path}' не является каталогом.[/red]")
                        continue
                    create_ans = input(f"Папка '{target_path}' не существует. Создать её? (y/n): ").strip().lower()
                    if create_ans == "y":
                        os.makedirs(target_path, exist_ok=True)
                    else:
                        console.print(f"[bold yellow]Переход отменен.[/bold yellow]")
                        continue

                current_dir = target_path
                console.print(f"[bold green]Текущая папка сменена на: {current_dir}[/bold green]")
                continue

            if first_line.startswith("/"):
                console.print(Text("Неизвестная команда. Используйте /help; сообщение не отправлено."))
                continue

            draft.text = user_input
            try:
                content = attachment_text(draft.message(user_input), draft.images)
                if len(content) > 32768:
                    raise ValueError("Сообщение с метаданными слишком большое")
                row = {"role": "user", "content": content}
                if draft.images:
                    row["images"] = encode_images(draft.images)
            except ValueError as error:
                console.print(Text(str(error)))
                continue
            try:
                preview = build_stream_payload(temporary_history + [row], chat_id, current_model, is_temporary,
                                               summary=summary, mcp=active_mcp(), skill=active_skill().payload())
            except ValueError as error:
                console.print(result_panel(str(error), title="Контекст", error=True))
                continue
            key = (backend_identity(api_client), chat_id)
            marker = (current_model, tuple((event.get("id"), event.get("status")) for event in temporary_history),
                      (summary or {}).get("boundary_id"))
            previous = auto_attempts.get(key, (None, None))
            if previous[0] != marker:
                try:
                    info = inspect_context(api_client, preview)
                    if isinstance(info, dict) and should_auto_compact(info):
                        result = compact_context(api_client, temporary_history, chat_id, current_model, summary,
                                                 blocked_fingerprint=previous[1])
                        if result.get("reason") == "cancelled":
                            console.print(result_panel("Сжатие отменено. Сообщение не отправлено; черновик сохранён.", title="Контекст"))
                            continue
                        if apply_summary(result):
                            auto_attempts.pop(key, None)
                            console.print(result_panel("Контекст автоматически сжат; полная история сохранена.", title="Контекст"))
                        else:
                            auto_attempts[key] = (marker, result.get("fingerprint"))
                            console.print(result_panel("Автосжатие не выполнено. Повтор той же попытки отключён; доступна /compact.", title="Контекст", error=True))
                except InterruptedError:
                    console.print(result_panel("Оценка отменена. Сообщение не отправлено; черновик сохранён.", title="Контекст"))
                    continue
                except Exception:
                    pass  # Unavailable provider metadata must not invent model limits.
            state = TurnState()
            row.update(id=str(uuid4()), turn_id=state.turn_id, status="running")
            changes_key = (backend_identity(api_client), chat_id, os.path.realpath(current_dir))
            if changes_key not in file_changes:
                if len(file_changes) >= 8:
                    console.print(result_panel("Журнал хранит до 8 чатов/папок; самый старый журнал освобождён.", title="Файловые правки"))
                    file_changes.pop(next(iter(file_changes)))
                file_changes[changes_key] = ChangeHistory(current_dir,
                    store=CheckpointStore(Path(CONFIG_DIR) / "checkpoints"))
            journal = file_changes[changes_key]
            state.changes = journal.begin_turn(state.turn_id)
            console.print("\n[bold cyan]Gemini:[/bold cyan]")
            temporary_history.append(row)
            bound_image_history(temporary_history)

            state.view = WorkView(console, state)
            turn = ToolTurn()
            tool_rounds = 0
            while True:
                tool_rounds += 1
                ending = tool_rounds > 12
                try:
                    payload = build_stream_payload(temporary_history, chat_id, current_model, is_temporary, turn,
                                                   end_tool_turn=ending, summary=summary, mcp=active_mcp(),
                                                   skill=active_skill().payload())
                except ValueError as error:
                    console.print(result_panel(str(error), title="Контекст", error=True))
                    break
                payload = state.request(payload)
                has_pending_tool = payload["continue_after_tool"]

                try:
                    state.view.update_text("")
                    with state.view.monitor():
                        response = open_stream(api_client, payload, state)
                except InterruptedError:
                    break
                except Exception:
                    notice = ("Черновик сохранён; повторите отправку." if draft.text or draft.items()
                              else "Запрос остаётся в истории; уже выполненные действия не повторяются автоматически.")
                    console.print(Text("Соединение прервано. " + notice))
                    break

                if response.status_code == 200:
                    # Once the backend accepts the turn, it is sent history,
                    # not an unsent draft (even if a later tool continuation fails).
                    draft.clear()
                    full_response, tool_calls_received = display_stream_response(
                        response, has_pending_tool, state)

                    if tool_calls_received:
                        if ending:
                            console.print("[yellow]Сервер не поддерживает завершение цепочки инструментов.[/yellow]")
                            break
                        if full_response:
                            temporary_history.append({"role": "model", "content": full_response, "id": str(uuid4()),
                                                  "turn_id": state.turn_id, "status": "running"})
                        execute_tool_calls(tool_calls_received, temporary_history, current_dir,
                                           turn=turn, api_client=api_client, state=state, mcp=active_mcp())
                        if state.cancelled.is_set():
                            break
                        console.print("[dim]Передаю результаты выполнения обратно на сервер...[/dim]")
                        continue

                    if full_response:
                        console.rule(style="dim #4285F4")
                        temporary_history.append({"role": "model", "content": full_response, "id": str(uuid4()),
                                                  "turn_id": state.turn_id, "status": "running"})
                        state.finish()
                        break

                    break

                else:
                    err_detail = "Неизвестная ошибка сервера"
                    try:
                        err_detail = response.json().get("detail", err_detail)
                    except Exception as e:
                        logger.exception(f"Необработанное исключение: {e}")

                    console.print(f"\n[red]Ошибка сервера ({response.status_code}): {err_detail}[/red]\n")
                    logger.error(f"Ошибка сервера ({response.status_code}): {err_detail}")
                    break

            if state.cancelled.is_set():
                row["status"] = "cancelled"
                notice = ("Черновик сохранён." if draft.text or draft.items()
                          else "Отправленный запрос остаётся в истории.")
                console.print(Text("Ход отменён. Выполненные действия и расход квоты не откатываются. " + notice))
            else:
                state.finish("failed")
            if state.status != "completed" and draft.text:
                draft.retry_pending = True
            for event in temporary_history:
                if event.get("turn_id") == state.turn_id:
                    event["status"] = state.status
            if state.changes.entries:
                console.print(result_panel(state.changes.summary() + "\n/diff — список · /diff путь — просмотр · /undo путь — откат файла", title="Файловые правки"))
            if journal.trim():
                console.print(result_panel("Старые ходы освобождены: журнал ограничен 32 ходами с правками и 64 МиБ.", title="Файловые правки"))
            remember()

        except KeyboardInterrupt:
            console.print("\n[yellow]Выход...[/yellow]")
            break
        except Exception as e:
            console.print(f"\n[red]Произошла ошибка соединения: {e}[/red]\n")
            logger.exception(f"Необработанное исключение: {e}")
            break


    for manager in mcp_managers.values():
        manager.close()
    preview_warning = draft_input.close()
    if preview_warning:
        console.print(Text(preview_warning))
    if settings:
        settings.close()


if __name__ == "__main__":
    main()

import os
import sys
import json
import ipaddress
import tempfile
from pathlib import Path
from contextlib import nullcontext
from typing import Optional, Dict, List, Any
from urllib.parse import urlsplit

import requests
from gemini_cli.backends.base import Backend, StreamResult
from gemini_cli.runtime.history import trim_history
from gemini_cli.backends.remote import RemoteBackend, events_from_response as iter_stream_events
from prompt_toolkit import PromptSession
from prompt_toolkit.shortcuts import radiolist_dialog
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
from gemini_cli.tools.local.files import read_files, write_files, read_file_lines
from gemini_cli.tools.local.search import find_files, search_text
from gemini_cli.tools.local.edit import replace_in_file
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


def confirm_replacement(diff: str) -> bool:
    console.print(Text(diff))
    try:
        return input("Применить показанный diff? (y/n): ").strip().lower() == "y"
    except (EOFError, KeyboardInterrupt):
        return False


def handle_read_files(args: dict, current_dir: str) -> str:
    return read_files(args, current_dir, approve=confirm_file_read, logger=logger)


def confirm_file_write(files: list[dict]) -> bool:
    table = Table(title="🚨 Запрос на запись/изменение файлов", show_header=True, header_style="bold yellow")
    table.add_column("Путь (относительно рабочей папки)", style="cyan")
    table.add_column("Размер (символов)", style="magenta")

    for f in files:
        table.add_row(f.get("filepath", "unknown"), str(len(f.get("content", ""))))

    console.print(table)

    for f in files:
        filepath = f.get("filepath", "unknown")
        content = f.get("content", "")
        console.print(Panel(content, title=f"📝 Предпросмотр: {filepath}", border_style="blue", expand=True))

    console.print("")
    confirm = input("Разрешить создание/модификацию этих файлов? (y/n): ").strip().lower()

    if confirm != 'y':
        console.print("[bold red]❌ Операция заблокирована пользователем.[/bold red]\n")
        return False

    return True


def handle_write_files(args: dict, current_dir: str) -> str:
    return write_files(args, current_dir, approve=confirm_file_write,
                       notify=console.print, logger=logger)


def confirm_command(command: str) -> bool:
    console.print(Panel(f"[bold white]{command}[/bold white]", title="⚙️ ИИ запрашивает выполнение команды терминала",
                        border_style="yellow"))

    confirm = input("Выполнить эту команду в вашей рабочей директории? (y/n): ").strip().lower()
    if confirm != 'y':
        console.print("[bold red]❌ Выполнение команды отменено пользователем.[/bold red]")
        return False

    return True


def handle_execute_command(args: dict, current_dir: str) -> str:
    return execute_command(args, current_dir, approve=confirm_command,
                           notify=console.print, logger=logger)


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


def show_chat_menu(client: Backend) -> Optional[tuple[Optional[str], bool]]:
    db_chats = client.get_chats()
    if db_chats is None:
        return None

    values = [
        ("temporary", "Войти во временный чат"),
        ("new", "+ Создать новую комнату диалога"),
    ]

    for c in db_chats:
        values.append((c["id"], f"Чат: {c['title']} ({c['created_at'][:10]})"))

    result = radiolist_dialog(
        title="Выбор комнаты",
        text="Выберите чат для работы или создайте новый:",
        values=values,
    ).run()

    if result is None:
        return None

    if result == "temporary":
        return None, True

    if result == "new":
        title = input("Введите название нового чата: ").strip()
        if not title:
            title = "Новый диалог"
        new_chat = client.create_chat(title)
        if new_chat:
            return new_chat["id"], False
        console.print("[red]Не удалось создать чат. Переключаем во временный режим.[/red]")
        return None, True

    return result, False


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
                         *, end_tool_turn: bool = False) -> Dict[str, Any]:
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
    elif is_temporary:
        payload["history"] = history[:-1]
    return payload


def execute_tool_calls(tool_calls: List[Dict[str, Any]], history: List[Dict[str, Any]],
                       current_dir: str, *, turn: ToolTurn | None = None, api_client: Backend | None = None) -> None:
    handlers = {
        "read_local_files": handle_read_files,
        "write_local_files": handle_write_files,
        "execute_command": handle_execute_command,
        "find_files": lambda args, cwd: json.dumps(find_files(args, cwd), ensure_ascii=False),
        "replace_in_file": lambda args, cwd: json.dumps(replace_in_file(
            args, cwd, approve=confirm_content_scope, confirm_diff=confirm_replacement), ensure_ascii=False),
        "read_file_lines": lambda args, cwd: json.dumps(read_file_lines(args, cwd, approve=confirm_content_scope),
                                                         ensure_ascii=False),
        "search_text": lambda args, cwd: json.dumps(search_text(args, cwd, approve=confirm_content_scope),
                                                     ensure_ascii=False),
    }
    if turn is not None and api_client is not None:
        def web_handler(kind, args):
            result = (turn.search(args, api_client.web_tool) if kind == "search"
                      else turn.read(args, api_client.web_tool))
            turn.report(kind, json.loads(result), lambda text: console.print(Text(text)))
            return result
        handlers["web_search"] = lambda args, _cwd: web_handler("search", args)
        handlers["read_url"] = lambda args, _cwd: web_handler("read", args)
    run_tool_calls(tool_calls, history, current_dir, handlers=handlers, logger=logger)



def display_stream_response(response, has_pending_tool: bool):
    full_response = ""
    tool_calls_received = []
    error_content = None
    status_text = ("[bold yellow]⚙️  Ожидаю ответ инструмента...[/bold yellow]"
                   if has_pending_tool else "[bold green]✨ Gemini думает...[/bold green]")
    use_screen = (console.is_terminal and not console.is_dumb_terminal
                  and not console.legacy_windows)
    with console.screen() if use_screen else nullcontext():
        status = console.status(status_text, spinner="dots")
        started_text = False
        line_ended = False
        status.start()
        try:
            for event in iter_stream_events(response):
                event_type = event.get("type")
                if event_type == "text":
                    fragment = event.get("content", "")
                    if fragment:
                        full_response += fragment
                        if not started_text:
                            status.stop()
                            started_text = True
                        sys.stdout.write(fragment)
                        sys.stdout.flush()
                        line_ended = fragment.endswith("\n")
                elif event_type == "tool_call":
                    tool_calls_received.append(event)
                elif event_type == "error":
                    error_content = event.get("content")
                    break
        finally:
            status.stop()
            close = getattr(response, "close", None)
            if close:
                close()
            if started_text and not line_ended:
                sys.stdout.write("\n")
                sys.stdout.flush()
    if error_content is not None:
        console.print(f"[bold red]Ошибка:[/] {error_content}")
        return "", []
    if use_screen and full_response and not tool_calls_received:
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
    if api_client is None:
        server_url = get_server_url()
        api_client = GeminiAPIClient(server_url)
        if not api_client.login():
            return

    current_model = "gemini-3.5-flash-lite"
    selected_chat = show_chat_menu(api_client)
    if selected_chat is None:
        return
    chat_id, is_temporary = selected_chat
    current_dir = os.getcwd()
    chat_mode = "ВРЕМЕННЫЙ" if is_temporary else "ПОСТОЯННЫЙ"
    print_banner(current_model, chat_mode, current_dir)

    session = PromptSession(key_bindings=bindings, style=my_style)

    temporary_history: List[Dict[str, str]] = []

    while True:
        try:
            dir_name = os.path.basename(current_dir) or current_dir
            prompt_text = f" {dir_name} › "
            user_input = session.prompt(HTML(
                f"<ansiblue>[{current_model}]</ansiblue>"
                f"<ansigray>{prompt_text}</ansigray>"
            ))

            if not user_input.strip():
                continue

            first_line = user_input.strip().split("\n")[0]
            if first_line.lower() in ["выход", "exit", "quit", "q", "й"]:
                console.print("[bold red]Рад был помочь![/bold red]")
                break

            if first_line.startswith("/help"):
                table = Table(title="Доступные команды Gemini-CLI", show_header=True, header_style="bold magenta")
                table.add_column("Команда", style="cyan")
                table.add_column("Описание", style="white")

                table.add_row("/help", "Показать эту справку")
                table.add_row("/model", "Сменить ИИ модель")
                table.add_row("/chat", "Сменить или создать комнату диалога")
                table.add_row("/delete", "Удалить текущий постоянный чат")
                table.add_row("/cd {путь}", "Изменить текущую рабочую папку для Gemini")
                table.add_row("exit, quit, q", "Выход из приложения")

                console.print(Panel(table, title="[bold green]Справка[/bold green]", expand=False))
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
                        temporary_history = []
                    else:
                        console.print("[red]Не удалось удалить чат.[/red]")
                continue


            if first_line.startswith("/model"):
                current_model = show_model_selection_menu(current_model)
                continue

            if first_line.startswith("/chat"):
                selected_chat = show_chat_menu(api_client)
                if selected_chat is None:
                    continue
                new_chat_id, new_is_temporary = selected_chat
                if new_chat_id != chat_id or new_is_temporary != is_temporary:
                    chat_id = new_chat_id
                    is_temporary = new_is_temporary
                    temporary_history = []
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

            console.print("\n[bold cyan]Gemini:[/bold cyan]")

            temporary_history.append({"role": "user", "content": user_input})

            turn = ToolTurn()
            tool_rounds = 0
            while True:
                tool_rounds += 1
                ending = tool_rounds > 12
                temporary_history = trim_history(temporary_history, 20)
                payload = build_stream_payload(temporary_history, chat_id, current_model, is_temporary, turn,
                                               end_tool_turn=ending)
                has_pending_tool = payload["continue_after_tool"]

                response = api_client.stream_chat(payload)

                if response.status_code == 200:
                    full_response, tool_calls_received = display_stream_response(
                        response, has_pending_tool)

                    if tool_calls_received:
                        if ending:
                            console.print("[yellow]Сервер не поддерживает завершение цепочки инструментов.[/yellow]")
                            break
                        if full_response:
                            temporary_history.append({"role": "model", "content": full_response})
                        execute_tool_calls(tool_calls_received, temporary_history, current_dir,
                                           turn=turn, api_client=api_client)
                        console.print("[dim]Передаю результаты выполнения обратно на сервер...[/dim]")
                        continue

                    if full_response:
                        console.rule(style="dim #4285F4")
                        temporary_history.append({"role": "model", "content": full_response})
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

        except KeyboardInterrupt:
            console.print("\n[yellow]Выход...[/yellow]")
            break
        except Exception as e:
            console.print(f"\n[red]Произошла ошибка соединения: {e}[/red]\n")
            logger.exception(f"Необработанное исключение: {e}")
            break


if __name__ == "__main__":
    main()

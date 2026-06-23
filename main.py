import os
import sys
import time
import json
from typing import Optional, Dict, List, Any

import requests
from prompt_toolkit import PromptSession
from prompt_toolkit.shortcuts import radiolist_dialog
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit import HTML
from prompt_toolkit.styles import Style

from rich.console import Console
from rich.markdown import Markdown
import subprocess
from rich.panel import Panel
from rich.table import Table
import logging
from datetime import datetime


LOG_FILE = os.path.join(os.path.expanduser("~"), ".gemini_cli", "gemini_cli.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

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

os.makedirs(CONFIG_DIR, exist_ok=True)


def get_server_url() -> str:
    if os.path.exists(SERVER_FILE):
        try:
            with open(SERVER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                url = data.get("server_url", "http://127.0.0.1:8000")
                if url:
                    return url
        except Exception as e:
            logger.exception(f"Необработанное исключение: {e}")

    console.print("[yellow]Конфигурация сервера не найдена.[/yellow]")
    url = input("Введите URL или IP вашего сервера (например, https://YOUR_VPS_IP:8000): ").strip()
    if not url:
        url = "http://127.0.0.1:8000"
    if not url.startswith("http://") and not url.startswith("https://"):
        if ":" in url:
            url = f"http://{url}"
        else:
            url = f"http://{url}:8000"

    with open(SERVER_FILE, "w", encoding="utf-8") as f:
        json.dump({"server_url": url}, f, ensure_ascii=False, indent=4)

    return url


def is_safe_path(base_dir: str, path: str) -> bool:
    absolute_base = os.path.abspath(base_dir)
    absolute_target = os.path.abspath(os.path.join(base_dir, path))
    return absolute_target.startswith(absolute_base)


def handle_read_files(args: dict, current_dir: str) -> str:
    filepaths = args.get("filepaths", [])
    if not filepaths:
        return json.dumps({"error": "Список файлов пуст"})

    console.print(f"\n[bold blue]📥 ИИ запрашивает чтение файлов ({len(filepaths)} шт.)...[/bold blue]")

    results = {}
    for path in filepaths:
        if not is_safe_path(current_dir, path):
            results[path] = "Ошибка: Доступ заблокирован песочницей"
            continue

        full_path = os.path.normpath(os.path.join(current_dir, path))
        if not os.path.exists(full_path):
            results[path] = "Ошибка: Файл не найден"
            continue

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                results[path] = f.read()
        except Exception as e:
            results[path] = f"Ошибка при чтении файла: {str(e)}"
            logger.exception(f"Необработанное исключение: {e}")

    return json.dumps(results, ensure_ascii=False)


def handle_write_files(args: dict, current_dir: str) -> str:
    files = args.get("files", [])
    if not files:
        return json.dumps({"error": "Список файлов для записи пуст"}, ensure_ascii=False)

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
        return json.dumps({"error": "Операция отклонена пользователем из соображений безопасности."},
                          ensure_ascii=False)

    results = []
    for f in files:
        rel_path = f.get("filepath", "")
        content = f.get("content", "")

        if not is_safe_path(current_dir, rel_path):
            results.append({"filepath": rel_path, "status": "Заблокировано песочницей"})
            continue

        full_path = os.path.normpath(os.path.join(current_dir, rel_path))
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(content)
            results.append({"filepath": rel_path, "status": "Успешно записан"})
        except Exception as e:
            results.append({"filepath": rel_path, "status": f"Ошибка: {str(e)}"})
            logger.exception(f"Необработанное исключение: {e}")

    console.print("[green]✔ Изменения успешно применены к диску.[/green]\n")
    return json.dumps(results, ensure_ascii=False)


def handle_execute_command(args: dict, current_dir: str) -> str:
    command = args.get("command", "").strip()
    if not command:
        return json.dumps({"error": "Команда пустая"})

    console.print(Panel(f"[bold white]{command}[/bold white]", title="⚙️ ИИ запрашивает выполнение команды терминала",
                        border_style="yellow"))

    confirm = input("Выполнить эту команду в вашей рабочей директории? (y/n): ").strip().lower()
    if confirm != 'y':
        console.print("[bold red]❌ Выполнение команды отменено пользователем.[/bold red]")
        return "Выполнение команды отменено пользователем."

    console.print("[green]Запуск процесса...[/green]")
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=current_dir,
            text=True,
            capture_output=True,
            timeout=120
        )

        response_data = {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
        return json.dumps(response_data, ensure_ascii=False)

    except subprocess.TimeoutExpired:
        console.print("[red]❌ Превышено время ожидания (лимит 2 минуты)[/red]")
        return json.dumps({"error": "Превышено время ожидания выполнения команды (Timeout 120s)"})
    except Exception as e:
        logger.exception(f"Необработанное исключение: {e}")
        return json.dumps({"error": f"Критическая ошибка вызова подпроцесса: {str(e)}"})



class GeminiAPIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.token: Optional[str] = None

    def set_token(self, token: str):
        self.token = token

    @property
    def headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _load_session_token(self) -> Optional[str]:
        if not os.path.exists(SESSION_FILE):
            return None

        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("access_token")
        except Exception as e:
            logger.exception(f"Необработанное исключение: {e}")
            return None

    def login(self):
        token = self._load_session_token()
        if token:
            self.set_token(token)
            return

        console.print("[bold cyan]Авторизируйтесь через email:[/bold cyan]")
        while True:
            email = input("Email: ").strip()
            password = PromptSession().prompt("Пароль: ", is_password=True).strip()

            if not email or not password:
                console.print("[yellow]Email и пароль не должны быть пустыми.[/yellow]")
                continue

            try:
                url = f"{self.base_url}/auth/login"
                payload = {"email": email, "password": password}
                r = requests.post(url, json=payload, timeout=30)

                if r.status_code == 200:
                    res_data = r.json()
                    token = res_data.get("access_token")
                    if not token:
                        console.print("[red]Сервер не вернул access_token[/red]")
                        continue

                    with open(SESSION_FILE, "w", encoding="utf-8") as f:
                        json.dump(res_data, f, ensure_ascii=False, indent=4)

                    self.set_token(token)
                    console.print("[green]Вход выполнен успешно.[/green]")
                    logger.info(f"Пользователь авторизован")
                    break
                else:
                    if r.status_code == 401:
                        console.print(
                            "[yellow]Не удалось войти: проверьте email, пароль или подтверждение на почте.[/yellow]")
                        ans = input("Создать новый аккаунт? (y/n): ").strip().lower()
                        if ans == "y":
                            s = requests.post(f"{self.base_url}/auth/signup", json=payload, timeout=30)
                            if s.status_code in (200, 201):
                                try:
                                    data = s.json()
                                except Exception as e:
                                    logger.exception(f"Необработанное исключение: {e}")
                                    data = {}

                                token = data.get("access_token") or (data.get("session") or {}).get("access_token")
                                if token:
                                    with open(SESSION_FILE, "w", encoding="utf-8") as f:
                                        json.dump(data, f, ensure_ascii=False, indent=4)
                                    self.set_token(token)
                                    console.print("[green]Аккаунт создан и вход выполнен.[/green]")
                                    logger.info("Новый аккаунт создан и авторизован")
                                    break
                                else:
                                    console.print(
                                        "[yellow]Аккаунт создан. Проверьте почту и подтвердите email.[/yellow]")
                            else:
                                console.print("[red]Не удалось создать аккаунт. Попробуйте позже.[/red]")
                        continue

                    console.print("[red]Не удалось выполнить вход. Попробуйте ещё раз.[/red]")

            except requests.RequestException:
                console.print("[red]Не удалось связаться с сервером. Проверьте, что сервер запущен.[/red]")
            except Exception as e:
                console.print("[red]Произошла непредвиденная ошибка входа.[/red]")
                logger.exception(f"Необработанное исключение: {e}")

    def get_chats(self) -> List[Dict[str, Any]]:
        try:
            r = requests.get(f"{self.base_url}/chats", headers=self.headers, timeout=30)
            if r.status_code == 200:
                return r.json()
            return []
        except Exception as e:
            console.print(f"[red]Ошибка при получении чатов: {e}[/red]")
            logger.exception(f"Необработанное исключение: {e}")
            return []

    def create_chat(self, title: str) -> Optional[Dict[str, Any]]:
        try:
            r = requests.post(
                f"{self.base_url}/chats",
                json={"title": title},
                headers=self.headers,
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()
            return None
        except Exception as e:
            console.print(f"[red]Ошибка при создании чата: {e}[/red]")
            logger.exception(f"Необработанное исключение: {e}")
            return None

    def delete_chat(self, chat_id: str) -> bool:
        try:
            r = requests.delete(
                f"{self.base_url}/chats/{chat_id}",
                headers=self.headers,
                timeout=30,
            )
            return r.status_code == 200
        except Exception as e:
            logger.error(f"Ошибка при удалении чата: {e}")
            console.print(f"[red]Ошибка при удалении чата: {e}[/red]")
            return False

def show_chat_menu(client: GeminiAPIClient) -> tuple[Optional[str], bool]:
    db_chats = client.get_chats()

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
        sys.exit(0)

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
        ("gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite"),
        ("gemini-2.5-flash", "Gemini 2.5 Flash"),
        ("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite"),
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


def trim_history(history: List[Dict[str, str]], limit: int = 20, tool_content_limit: int = 4) -> List[Dict[str, str]]:
    if len(history) <= limit:
        trimmed = history
    else:
        trimmed = history[-limit:]
        while trimmed and trimmed[0].get("role") == "tool":
            trimmed = trimmed[1:]

    tool_count = 0
    for msg in reversed(trimmed):
        if msg.get("role") == "tool":
            tool_count += 1
            if tool_count > tool_content_limit:
                msg["content"] = '{"status": "already_processed"}'

    return trimmed


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

def main():
    server_url = get_server_url()
    api_client = GeminiAPIClient(server_url)

    api_client.login()

    current_model = "gemini-3.1-flash-lite"
    chat_id, is_temporary = show_chat_menu(api_client)
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
                new_chat_id, new_is_temporary = show_chat_menu(api_client)
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

                target_path = os.path.abspath(parts[1])

                if not os.path.exists(target_path):
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

            while True:
                last_msg = temporary_history[-1] if temporary_history else None
                has_pending_tool = last_msg is not None and last_msg.get("role") == "tool"

                if has_pending_tool:
                    user_msg = next(
                        (msg["content"] for msg in reversed(temporary_history) if msg.get("role") == "user"), "")
                    payload_message = user_msg if user_msg else "Продолжай работу на основе ответов инструментов."
                else:
                    payload_message = temporary_history[-1]["content"] if temporary_history and temporary_history[
                        -1].get("role") == "user" else ""

                payload: Dict[str, Any] = {
                    "message": payload_message,
                    "chat_id": chat_id,
                    "model_name": current_model,
                }

                temporary_history = trim_history(temporary_history, 20)

                if is_temporary or has_pending_tool:
                    payload["history"] = temporary_history

                response = requests.post(
                    f"{api_client.base_url}/chat/stream",
                    json=payload,
                    headers=api_client.headers,
                    stream=True,
                    timeout=300,
                )

                if response.status_code == 200:
                    full_response = ""
                    tool_call_received = None

                    status_text = f"[bold yellow]⚙️  Выполнение...[/bold yellow]" if has_pending_tool else "[bold green]✨ Gemini думает...[/bold green]"
                    with console.status(status_text, spinner="dots"):

                        for raw_line in response.iter_lines():
                            if not raw_line:
                                continue

                            line = raw_line.decode("utf-8").strip()

                            if line.startswith("data: "):
                                body = line[6:]
                                try:
                                    event = json.loads(body)
                                    event_type = event.get("type")

                                    if event_type == "text":
                                        full_response += event.get("content", "")

                                    elif event_type == "tool_call":
                                        tool_call_received = event
                                        break

                                    elif event_type == "error":
                                        console.print(f"\n[bold red]Ошибка от Gemini:[/] {event.get('content')}")
                                        break
                                except Exception as e:
                                    logger.exception(f"Необработанное исключение: {e}")


                    if tool_call_received:
                        tool_name = tool_call_received.get("name")
                        tool_args = tool_call_received.get("args", {})

                        temporary_history.append({
                            "role": "model",
                            "content": f"[Вызов локального инструмента: {tool_name}]",
                            "name": tool_name,
                            "args": tool_args
                        })

                        if tool_name == "read_local_files":
                            tool_result = handle_read_files(tool_args, current_dir)
                        elif tool_name == "write_local_files":
                            tool_result = handle_write_files(tool_args, current_dir)
                        elif tool_name == "execute_command":
                            tool_result = handle_execute_command(tool_args, current_dir)
                        else:
                            tool_result = f"Ошибка: Инструмент {tool_name} не поддерживается клиентом."

                        temporary_history.append({
                            "role": "tool",
                            "name": tool_name,
                            "content": tool_result
                        })

                        console.print("[dim]Передаю результаты выполнения обратно на сервер...[/dim]")
                        logger.info(f"Tool вызов: {tool_name}, args: {tool_args}")
                        continue

                    if full_response:
                        with console.capture() as capture:
                            console.print(Markdown(full_response))
                        rendered_markdown = capture.get()

                        lines = rendered_markdown.splitlines(keepends=True)
                        for line in lines:
                            sys.stdout.write(line)
                            sys.stdout.flush()
                            if len(line.strip()) > 0:
                                time.sleep(0.012)

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
import os
import sys
import json
import ipaddress
import tempfile
import stat
from contextlib import nullcontext
from typing import Optional, Dict, List, Any
from urllib.parse import urlsplit

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
from rich.text import Text
import logging
from datetime import datetime


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
        port = "" if parsed.port is not None else ":8000"
        url = f"{scheme}:{url}{port}"

    parsed = urlsplit(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Укажите URL сервера без пути и учётных данных (HTTP или HTTPS)")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Некорректный порт сервера")
    if parsed.scheme == "http" and not is_loopback_host(parsed.hostname):
        raise ValueError("Для удалённого сервера требуется HTTPS")
    return f"{parsed.scheme}://{parsed.netloc}"


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
            url = normalize_server_url(input("Введите URL или IP вашего сервера (например, https://YOUR_VPS_IP:8000): "))
            break
        except ValueError as e:
            console.print(f"[red]{e}[/red]")

    with open(SERVER_FILE, "w", encoding="utf-8") as f:
        json.dump({"server_url": url}, f, ensure_ascii=False, indent=4)

    return url


def resolve_safe_path(base_dir: str, path: str) -> Optional[str]:
    resolved_base = os.path.realpath(base_dir)
    resolved_target = os.path.realpath(os.path.join(base_dir, path))
    try:
        if os.path.commonpath((resolved_base, resolved_target)) == resolved_base:
            return resolved_target
    except ValueError:
        pass
    return None


def is_sensitive_read_path(path: str) -> bool:
    parts = [part.casefold() for part in os.path.normpath(path).split(os.sep)]
    name = parts[-1]
    return (any(part == ".env" or part.startswith(".env.") for part in parts)
            or name in {".envrc", ".netrc", ".npmrc", ".pypirc", "credentials.json",
                        "service-account.json", "service_account.json", "session.json",
                        "id_rsa", "id_ed25519"}
            or name.endswith((".pem", ".key")))


def file_identity(file_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (file_stat.st_dev, file_stat.st_ino, file_stat.st_size,
            file_stat.st_mtime_ns, file_stat.st_ctime_ns)


def handle_read_files(args: dict, current_dir: str) -> str:
    filepaths = args.get("filepaths", [])
    if not filepaths:
        return json.dumps({"error": "Список файлов пуст"})

    planned = []
    for path in filepaths:
        full_path = resolve_safe_path(current_dir, path)
        expected_identity = None
        if full_path is None:
            error = "Ошибка: Доступ заблокирован песочницей"
        elif is_sensitive_read_path(full_path):
            error = "Ошибка: Чтение файла с секретами запрещено"
        else:
            error = None
            try:
                expected_identity = file_identity(os.stat(full_path))
            except FileNotFoundError:
                error = "Ошибка: Файл не найден"
            except OSError as e:
                error = f"Ошибка при чтении файла: {e}"
        planned.append((path, full_path, error, expected_identity))

    readable = [(path, full_path) for path, full_path, error, _ in planned if error is None]
    approved = False
    if readable:
        table = Table(title="ИИ запрашивает чтение файлов")
        table.add_column("Запрошенный путь")
        table.add_column("Файл")
        for path, full_path in readable:
            table.add_row(Text(repr(path)), Text(full_path))
        console.print(table)
        try:
            approved = input("Разрешить чтение и отправку содержимого этих файлов модели? (y/n): ").strip().lower() == "y"
        except (EOFError, KeyboardInterrupt):
            approved = False

    results = {}
    for path, full_path, error, expected_identity in planned:
        if error:
            results[path] = error
            continue
        if not approved:
            results[path] = "Ошибка: Чтение отклонено пользователем"
            continue

        try:
            with os.fdopen(os.open(full_path, os.O_RDONLY), "r", encoding="utf-8") as f:
                if file_identity(os.fstat(f.fileno())) != expected_identity:
                    results[path] = "Ошибка: Файл изменился после подтверждения"
                    continue
                content = f.read()
                if file_identity(os.fstat(f.fileno())) != expected_identity:
                    results[path] = "Ошибка: Файл изменился во время чтения"
                    continue
                results[path] = content
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

        full_path = resolve_safe_path(current_dir, rel_path)
        if full_path is None:
            status = "Заблокировано песочницей"
            results.append({"filepath": rel_path, "status": status})
            console.print(f"{rel_path}: {status}")
            continue

        temporary_path = None
        try:
            directory = os.path.dirname(full_path)
            os.makedirs(directory, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                             prefix=".gemini-write-", delete=False) as file_obj:
                temporary_path = file_obj.name
                file_obj.write(content)
            if os.path.exists(full_path):
                os.chmod(temporary_path, stat.S_IMODE(os.stat(full_path).st_mode))
            os.replace(temporary_path, full_path)
            status = "Успешно записан"
        except Exception as e:
            status = f"Ошибка: {str(e)}"
            logger.exception(f"Необработанное исключение: {e}")
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)
        results.append({"filepath": rel_path, "status": status})
        console.print(f"{rel_path}: {status}")

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
        self.base_url = normalize_server_url(base_url)
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

    def _renew_session(self) -> bool:
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as file:
                refresh_token = json.load(file).get("refresh_token")
        except (OSError, ValueError, AttributeError):
            refresh_token = None

        if refresh_token:
            try:
                response = requests.post(
                    f"{self.base_url}/auth/refresh",
                    json={"refresh_token": refresh_token}, timeout=30,
                    allow_redirects=False,
                )
            except requests.RequestException as e:
                console.print(f"[red]Не удалось обновить сессию: {e}[/red]")
                return False
            if response.status_code == 200:
                data = response.json()
                if data.get("access_token") and data.get("refresh_token"):
                    save_session(data)
                    self.set_token(data["access_token"])
                    return True
            elif response.status_code not in (400, 401, 403):
                console.print("[red]Сервер временно не может обновить сессию.[/red]")
                return False

        self.token = None
        try:
            os.unlink(SESSION_FILE)
        except FileNotFoundError:
            pass
        console.print("[yellow]Сессия истекла. Войдите снова.[/yellow]")
        self.login()
        return bool(self.token)

    def _authorized_request(self, request):
        response = request()
        if response.status_code != 401:
            return response
        response.close()
        if not self._renew_session():
            return response
        return request()

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
                r = requests.post(url, json=payload, timeout=30, allow_redirects=False)

                if r.status_code == 200:
                    res_data = r.json()
                    token = res_data.get("access_token")
                    if not token:
                        console.print("[red]Сервер не вернул access_token[/red]")
                        continue

                    save_session(res_data)

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
                            s = requests.post(f"{self.base_url}/auth/signup", json=payload, timeout=30,
                                              allow_redirects=False)
                            if s.status_code in (200, 201):
                                try:
                                    data = s.json()
                                except Exception as e:
                                    logger.exception(f"Необработанное исключение: {e}")
                                    data = {}

                                token = data.get("access_token") or (data.get("session") or {}).get("access_token")
                                if token:
                                    save_session(data.get("session") or data)
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

    def get_chats(self) -> Optional[List[Dict[str, Any]]]:
        try:
            r = self._authorized_request(lambda: requests.get(
                f"{self.base_url}/chats", headers=self.headers, timeout=30,
                allow_redirects=False))
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401:
                console.print("[red]Сессия истекла. Войдите снова.[/red]")
            else:
                console.print(f"[red]Не удалось получить список чатов (код {r.status_code}).[/red]")
            return None
        except Exception as e:
            console.print(f"[red]Ошибка при получении чатов: {e}[/red]")
            logger.exception(f"Необработанное исключение: {e}")
            return None

    def create_chat(self, title: str) -> Optional[Dict[str, Any]]:
        try:
            r = self._authorized_request(lambda: requests.post(
                f"{self.base_url}/chats",
                json={"title": title},
                headers=self.headers,
                timeout=30,
                allow_redirects=False,
            ))
            if r.status_code == 200:
                return r.json()
            return None
        except Exception as e:
            console.print(f"[red]Ошибка при создании чата: {e}[/red]")
            logger.exception(f"Необработанное исключение: {e}")
            return None

    def delete_chat(self, chat_id: str) -> bool:
        try:
            r = self._authorized_request(lambda: requests.delete(
                f"{self.base_url}/chats/{chat_id}",
                headers=self.headers,
                timeout=30,
                allow_redirects=False,
            ))
            return r.status_code == 200
        except Exception as e:
            logger.error(f"Ошибка при удалении чата: {e}")
            console.print(f"[red]Ошибка при удалении чата: {e}[/red]")
            return False

    def stream_chat(self, payload: Dict[str, Any]):
        return self._authorized_request(lambda: requests.post(
            f"{self.base_url}/chat/stream", json=payload,
            headers=self.headers, stream=True, timeout=300,
            allow_redirects=False,
        ))

def show_chat_menu(client: GeminiAPIClient) -> Optional[tuple[Optional[str], bool]]:
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


def trim_history(history: List[Dict[str, str]], limit: int = 20, tool_content_limit: int = 4) -> List[Dict[str, str]]:
    last_user = next((index for index in range(len(history) - 1, -1, -1)
                      if history[index].get("role") == "user"), len(history))
    start = min(max(0, len(history) - limit), last_user)
    trimmed = history[start:]
    while trimmed and trimmed[0].get("role") != "user":
        trimmed = trimmed[1:]

    tool_count = 0
    current_turn_start = next((index for index in range(len(trimmed) - 1, -1, -1)
                               if trimmed[index].get("role") == "user"), len(trimmed))
    for msg in reversed(trimmed[:current_turn_start]):
        if msg.get("role") == "tool":
            tool_count += 1
            if tool_count > tool_content_limit:
                msg["content"] = '{"status": "already_processed"}'

    return trimmed


def build_stream_payload(history: List[Dict[str, Any]], chat_id: Optional[str],
                         model_name: str, is_temporary: bool) -> Dict[str, Any]:
    continuing = bool(history and history[-1].get("role") == "tool")
    payload: Dict[str, Any] = {
        "message": "" if continuing else history[-1]["content"],
        "chat_id": chat_id,
        "model_name": model_name,
        "continue_after_tool": continuing,
    }
    if continuing:
        payload["history"] = history
    elif is_temporary:
        payload["history"] = history[:-1]
    return payload


def execute_tool_calls(tool_calls: List[Dict[str, Any]], history: List[Dict[str, Any]],
                       current_dir: str) -> None:
    for call in tool_calls:
        tool_name = call.get("name")
        history.append({
            "role": "model", "content": f"[Вызов локального инструмента: {tool_name}]",
            "name": tool_name, "args": call.get("args", {}), "call_id": call.get("call_id"),
            "thought_signature": call.get("thought_signature")
        })

    for call in tool_calls:
        tool_name = call.get("name")
        tool_args = call.get("args", {})
        if tool_name == "read_local_files":
            tool_result = handle_read_files(tool_args, current_dir)
        elif tool_name == "write_local_files":
            tool_result = handle_write_files(tool_args, current_dir)
        elif tool_name == "execute_command":
            tool_result = handle_execute_command(tool_args, current_dir)
        else:
            tool_result = f"Ошибка: Инструмент {tool_name} не поддерживается клиентом."
        history.append({
            "role": "tool", "name": tool_name, "content": tool_result,
            "call_id": call.get("call_id")
        })
        logged_name = tool_name if tool_name in (
            "read_local_files", "write_local_files", "execute_command"
        ) else "unknown"
        logger.info("Tool вызов: %s", logged_name)


def iter_stream_events(response):
    for raw_line in response.iter_lines():
        if not raw_line:
            continue
        try:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            yield json.loads(line[6:])
        except (ValueError, UnicodeError) as e:
            logger.exception(f"Некорректное событие потока: {e}")


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

def main():
    server_url = get_server_url()
    api_client = GeminiAPIClient(server_url)

    api_client.login()

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

            while True:
                temporary_history = trim_history(temporary_history, 20)
                payload = build_stream_payload(temporary_history, chat_id, current_model, is_temporary)
                has_pending_tool = payload["continue_after_tool"]

                response = api_client.stream_chat(payload)

                if response.status_code == 200:
                    full_response, tool_calls_received = display_stream_response(
                        response, has_pending_tool)

                    if tool_calls_received:
                        execute_tool_calls(tool_calls_received, temporary_history, current_dir)
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

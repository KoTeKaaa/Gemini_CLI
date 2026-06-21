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
from rich.live import Live

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
        except Exception:
            pass

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
        except Exception:
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
                                except Exception:
                                    data = {}

                                token = data.get("access_token") or (data.get("session") or {}).get("access_token")
                                if token:
                                    with open(SESSION_FILE, "w", encoding="utf-8") as f:
                                        json.dump(data, f, ensure_ascii=False, indent=4)
                                    self.set_token(token)
                                    console.print("[green]Аккаунт создан и вход выполнен.[/green]")
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
            except Exception:
                console.print("[red]Произошла непредвиденная ошибка входа.[/red]")

    def get_chats(self) -> List[Dict[str, Any]]:
        try:
            r = requests.get(f"{self.base_url}/chats", headers=self.headers, timeout=30)
            if r.status_code == 200:
                return r.json()
            return []
        except Exception as e:
            console.print(f"[red]Ошибка при получении чатов: {e}[/red]")
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
            return None


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
        ("gemini-3.5-flash", "Gemini 3.5 Flash"),
        ("gemini-2.5-flash", "Gemini 2.5 Flash"),
        ("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite"),
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
    return result


def trim_history(history: List[Dict[str, str]], limit: int = 20) -> List[Dict[str, str]]:
    if len(history) <= limit:
        return history
    return history[-limit:]



def main():
    server_url = get_server_url()
    api_client = GeminiAPIClient(server_url)

    api_client.login()

    chat_id, is_temporary = show_chat_menu(api_client)

    chat_mode = "ВРЕМЕННЫЙ" if is_temporary else "ПОСТОЯННЫЙ"
    console.print(f"[bold yellow]Сессия запущена! Режим: {chat_mode}[/bold yellow]")
    console.print("[gray](Для выхода нажмите 'Ctrl + C', для смены модели напишите '/model', для смены чата напишите '/chat')[/gray]\n")

    current_model = "gemini-3.1-flash-lite"
    session = PromptSession(key_bindings=bindings, style=my_style)

    temporary_history: List[Dict[str, str]] = []

    while True:
        try:
            prompt_text = f"Вы [{current_model}]: "
            user_input = session.prompt(HTML(f"<ansigreen>{prompt_text}</ansigreen>"))

            if not user_input.strip():
                continue

            first_line = user_input.strip().split("\n")[0]
            if first_line.lower() in ["выход", "exit", "quit", "q", "й"]:
                console.print("[bold red]Рад был помочь![/bold red]")
                break

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

            console.print("\n[bold cyan]Gemini:[/bold cyan]")

            payload: Dict[str, Any] = {
                "message": user_input,
                "chat_id": chat_id,
                "model_name": current_model,
            }

            if is_temporary:
                temporary_history = trim_history(temporary_history, 20)
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

                with console.status("[bold green]Gemini думает...", spinner="dots"):
                    for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                        if chunk:
                            full_response += chunk


                with console.capture() as capture:
                    console.print(Markdown(full_response))
                rendered_markdown = capture.get()


                lines = rendered_markdown.splitlines(keepends=True)

                for line in lines:
                    sys.stdout.write(line)
                    sys.stdout.flush()

                    if len(line.strip()) > 0:
                        time.sleep(0.012)

                console.print(f"\n[dim]{'-' * 40}[/dim]\n")


                if is_temporary:
                    temporary_history.append({"role": "user", "content": user_input})
                    temporary_history.append({"role": "model", "content": full_response})
                    temporary_history = trim_history(temporary_history, 20)

            else:
                err_detail = "Неизвестная ошибка сервера"
                try:
                    err_detail = response.json().get("detail", err_detail)
                except Exception:
                    pass
                console.print(f"\n[red]Ошибка сервера ({response.status_code}): {err_detail}[/red]\n")

        except KeyboardInterrupt:
            console.print("\n[yellow]Выход...[/yellow]")
            break
        except Exception as e:
            console.print(f"\n[red]Произошла ошибка соединения: {e}[/red]\n")


if __name__ == "__main__":
    main()
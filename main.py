import time
import os
import requests
from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit import print_formatted_text, HTML
from prompt_toolkit.styles import Style

from rich.console import Console
from rich.markdown import Markdown
from rich.live import Live

my_style = Style.from_dict({
    '': 'ansibrightgreen',
})

bindings = KeyBindings()

@bindings.add(Keys.Enter)
def _(event):
    event.current_buffer.validate_and_handle()

@bindings.add('c-j')
def _(event):
    event.current_buffer.newline()

load_dotenv()
vps_ip = os.getenv("VPS_IP")
SERVER_URL = f"http://{vps_ip}:8000/chat/stream"

def main():
    console = Console()

    console.print("[bold yellow]Привет! Я Gemini, чем я могу тебе помочь?[/bold yellow]")
    console.print("[gray](Для выхода напиши 'выход', а для переноса строки 'Ctrl + Enter')[/gray]\n")

    session = PromptSession(key_bindings=bindings, style=my_style)
    while True:
        try:
            user_input = session.prompt(HTML('<ansigreen>Вы: </ansigreen>'))

            first_line = user_input.strip().split("\n")[0].lower()
            if first_line in ['выход', 'exit', 'quit', 'q', 'й']:
                console.print("[bold red]Рад был помочь![/bold red]")
                break

            if not user_input.strip():
                continue

            console.print("\n[bold cyan]Gemini:[/bold cyan]")

            response = requests.post(
                SERVER_URL,
                json={"message": user_input},
                stream=True
            )

            if response.status_code == 200:
                full_response = ""
                with Live(
                        console=console,
                        refresh_per_second=60,
                        auto_refresh=True,
                        vertical_overflow="visible",
                        transient=True,
                ) as live:
                      for char in response.iter_content(chunk_size=1 ,decode_unicode=True):
                        if char:
                            full_response += char
                            live.update(Markdown(full_response))
                            time.sleep(0.008)

                console.print(Markdown(full_response))

                console.print(f"\n[dim]{'-'*40}[/dim]\n")
            else:
                console.print(f"\n[red]Ошибка сервера: {response.status_code}[/red]\n")
        except KeyboardInterrupt:
            console.print("\n[yellow]Выход...[/yellow]")
            break

        except Exception as e:
            console.print(f"\n[red]Произошла ошибка соединения: {e}[/red]\n")

if __name__ == "__main__":
    main()
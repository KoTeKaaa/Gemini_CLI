"""Статическая справка: без чтения настроек, подключения сервисов или LLM."""
from .input import result_panel

HELP = '''ИНСТРУМЕНТЫ РАЗРАБОТКИ

1. Поиск кода
Попросите: «Покажи python_symbols по имени Parser».
Карта содержит пути, строки, определения AST и синтаксические импорты.
find_files/search_text остаются доступны без LSP.

2. Точные ссылки, диагностика, rename (Python)
Установите отдельно: python -m pip install "python-lsp-server[rope,pyflakes]==1.15.0"
Доступен Python 3.9+; CLI требует Python 3.10+.
Перед запуском CLI явно задайте абсолютный GEMINI_CLI_PYLSP:
Linux: export GEMINI_CLI_PYLSP=/opt/example/pylsp/bin/pylsp
PowerShell: $env:GEMINI_CLI_PYLSP='C:\\Tools\\pylsp\\Scripts\\pylsp.exe'
Используйте только доверенный workspace: сервер может читать проект/его конфигурацию.
Пример: «Найди definition через python_lsp в src/app.py, line=10, character=4».
Строки с единицы; колонки UTF-16 с нуля; учитываются сохранённые файлы.
Другие action: references, diagnostics, rename (new_name=новое_имя).
Rename показывает содержимое и diff, требует подтверждения и проверяет версии.
Проверяйте результат; откат файлов через /undo, просмотр через /diff.

3. Проверки
Пример: «Запусти run_tests modules=[tests.test_parser] timeout=120».
Тесты исполняют код проекта после подтверждения. Пустой список — discovery tests/.
В exe укажите GEMINI_CLI_PYTHON на абсолютный путь Python окружения проекта.
Таймаут/отмена/пустой набор/отсутствующий итог не считаются успехом.
affected_tests files=[src/parser.py] рекомендует проверки по явным импортам.
Неизвестное влияние и конфигурационные изменения требуют полной регрессии.

4. Git и коммит
Попросите git_read action=status|diff|log|blame files=[src/app.py].
Для staged diff: staged=true. Вывод ограничен; скрытого staging нет.
Попросите подготовить git_commit action=prepare с files/message/task.
После просмотра используйте action=commit с одноразовым token и подтвердите.
Выбираются целые файлы, включая их staged/unstaged содержимое; посторонние
правки сохраняются. Hooks выполняются. После запуска commit дождитесь его
завершения: Esc остановит дальнейшие действия, но не прервёт hooks/index.
Публикация и merge в этот инструмент не входят.

5. PR через уже включённый персональный GitHub MCP
Настройка и вход: /mcp help. Выберите инструменты list_pull_requests,
create_pull_request, update_pull_request, pull_request_read.
Read-only доступ недостаточен для публикации: нужны PR write и Checks/Statuses read
только выбранного репозитория. Токены вводятся только через /mcp login, не в чат.
Ветка опубликована отдельно, origin на github.com.
Явно попросите github_pr action=create base=dev title=... body=... .
Создаётся draft; повтор возвращает существующий PR той же ветки/base.
action=update меняет описание; action=checks читает статус и проверки.
Каждый MCP-вызов подтверждается. Автоматического push/merge нет.
Неизвестный результат публикации сначала проверьте на GitHub, не повторяйте вслепую.
'''


def command(text: str, *, console, viewer) -> None:
    if text.strip() in {'/dev', '/dev help'}:
        viewer(HELP, title='/dev help · ↑↓/PgUp/PgDn — прокрутка · Esc — закрыть')
    else:
        console.print(result_panel('Использование: /dev help. Пример: /dev help — настройка LSP, тестов и Git/PR.',
                                   title='Разработка', error=True))

# GitHub MCP: Linux и Windows

[Русский](mcp-github.md) · [English](en/mcp-github.md)

Используется [официальный GitHub MCP](https://github.com/github/github-mcp-server).
Для удалённого Streamable HTTP не нужны Node/Docker. Нужны интернет, актуальный
CLI с MCP-зависимостями и персональный GitHub bearer. Подключение не отменяет
тарифы/ограничения GitHub API; 401 требует проверки токена, 429 — ожидания по
правилам сервиса, без скрытого повтора операции.

## Авторизация и минимальные права

В GitHub Settings → Developer settings → Personal access tokens создайте
fine-grained token с коротким сроком. Для первого теста выберите только
**Public repositories**, без дополнительных account permissions и без записи.
Создание/повторный вход в GitHub выполняет пользователь. Для приватных
репозиториев отдельно выберите только нужные repos и минимальные read permissions;
это расширение доступа не требуется для проверки публичного LICENSE.

Не вставляйте токен в чат модели, argv, URL, JSON-конфигурацию или Git.
Используйте запись `github` из [основного гайда](mcp.md), затем в CLI:

```text
/mcp login github memory
/mcp tools github
/mcp enable github
```

Токен вводится в скрытом поле. В Windows keyring использует Windows Credential
Manager; в Linux — Secret Service с разблокированным хранилищем. Если постоянное
хранение недоступно, явно выберите `memory`. Авторизация общего CLI Remote
и персональная авторизация GitHub MCP независимы.

## Linux

Для установки из исходников выполните в окружении проекта:

```bash
.venv/bin/python -m pip install -r client/requirements-mcp.txt
```

Сохраните `mcp.json` в `$HOME/.gemini_cli`, войдите и включите набор командами выше.
Не устанавливайте GitHub MCP на сервер приложения.

## Windows PowerShell

Полная exe-сборка содержит SDK. Для запуска из исходников:

```powershell
.\.venv-win\Scripts\python.exe -m pip install -r client\requirements-mcp.txt
```

Создайте тот же `mcp.json` в `$env:USERPROFILE\.gemini_cli`, выполните вход и enable.
Не используйте секрет в PowerShell-переменной/истории команд вместо скрытого ввода.

## Пробный вызов и удаление

Попросите: «Через GitHub MCP прочитай LICENSE публичного репозитория
`github/github-mcp-server`; только чтение». Перед `y` проверьте сервис,
`get_file_contents` и аргументы `owner=github`, `repo=github-mcp-server`, `path=LICENSE`.
В каталоге должен быть доступен именно этот инструмент; unsupported schema
показывается с причиной и не объявляется модели.

После теста: `/mcp disable github`, `/mcp logout github`. Удалите запись из
приватного `mcp.json` и перезапустите CLI, если подключение больше не нужно.
Отзовите временный токен в GitHub Settings самостоятельно. Read-only endpoint
ограничивает инструменты сервера, а права токена остаются отдельным ограничением.

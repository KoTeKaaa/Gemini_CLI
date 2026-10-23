# Playwright MCP: Linux и Windows

[Русский](mcp-playwright.md) · [English](en/mcp-playwright.md)

Используется [официальный Playwright MCP](https://github.com/microsoft/playwright-mcp),
закреплённая версия `@playwright/mcp@0.0.83`; Node.js 18+ (для новых установок
предпочтителен поддерживаемый Node LTS), npm и совместимый браузер. Проверка
ниже только интеграционная: отдельный профиль и список вкладок без входа
на сайты. Полный браузерный workflow описывается отдельно.

## Linux

Установите зависимости в отдельный пользовательский каталог:

```bash
MCP_INSTALL_DIR="$HOME/.local/share/gemini-cli-mcp"
npm install --prefix "$MCP_INSTALL_DIR" @playwright/mcp@0.0.83
node "$MCP_INSTALL_DIR/node_modules/playwright/cli.js" install chromium
node -e "console.log(require('$MCP_INSTALL_DIR/node_modules/playwright').chromium.executablePath())"
```

Последняя команда показывает путь Chromium для `--executable-path`. На системе
могут понадобиться системные зависимости браузера по документации Playwright;
их установка — отдельное действие владельца системы. Не отключайте sandbox
или TLS для обхода ошибки установки/запуска.

В приватный `mcp.json` добавьте запись, заменив оба абсолютных пути:

```json
{"name":"playwright","transport":"stdio","command":"node",
 "args":["/absolute/install/node_modules/@playwright/mcp/cli.js",
         "--headless","--isolated","--executable-path","/absolute/chromium/chrome"],
 "tools":["browser_tabs","browser_snapshot"],"timeout":30}
```

Это запись внутри массива `servers`, не отдельный project config.
`--isolated` создаёт отдельный профиль; не подключайте текущий личный браузер
через extension/CDP и не передавайте cookies/профиль из других приложений.

## Windows PowerShell

Установите Node LTS, затем в отдельный каталог:

```powershell
$mcpInstallDir = Join-Path $env:LOCALAPPDATA 'gemini-cli-mcp'
npm install --prefix $mcpInstallDir @playwright/mcp@0.0.83
node (Join-Path $mcpInstallDir 'node_modules\playwright\cli.js') install chromium
```

Получите путь браузера через установленный `playwright.chromium.executablePath()`.
Используйте ту же запись в `$env:USERPROFILE\.gemini_cli\mcp.json`, заменив
`command` на полный путь `node.exe`, а оба аргумента — на Windows-пути с
экранированными обратными слешами (`C:\\...`). Прямой запуск Node с `cli.js`
избегает неоднозначности `npx.cmd` и shell-quoting. npm/браузер устанавливаются
явно; чтение MCP config не запускает установку.

## Проверка и отключение

```text
/mcp check playwright
/mcp tools playwright
/mcp enable playwright
```

Попросите модель выполнить только `browser_tabs` с `action=list` и подтвердите
ровно этот вызов. Ожидается список вкладок отдельного браузера, обычно about:blank.
Ошибка отсутствующего браузера — ошибка проверки, не успешный read-only вызов.
Текст/дерево ограничиваются общим пределом MCP; screenshots/media не добавляются
как base64-текст. Сервис не требует личного токена для локального stdio, но сайты,
которые будут открываться позже, могут иметь собственную авторизацию и тарифы.

`/mcp disable playwright` завершает SDK-процесс и его управляемые потомки.
Удалите запись из приватного config и пользовательский каталог установки,
если интеграция больше не нужна. Установленный браузер может использоваться
другими Playwright-проектами: удаляйте общий cache только осознанно.

# Инструменты разработки

`python_symbols` строит ограниченную карту Python с путями и строками.
Чтение требует подтверждения; синтаксические импорты не доказывают полноту зависимостей.
Без language server доступны карта проекта, `find_files` и `search_text`.

## Python language server

Опциональный [python-lsp-server 1.15.0](https://pypi.org/project/python-lsp-server/)
под MIT поддерживает Python 3.9+, Linux и Windows. Клиенту нужен Python 3.10+.
Jedi предоставляет definitions/references; extras Rope и Pyflakes — rename и диагностику.
Установите отдельно от приложения, без общего обновления его зависимостей:

```sh
python -m venv /opt/example/pylsp
/opt/example/pylsp/bin/python -m pip install -r client/requirements-lsp.txt
/opt/example/pylsp/bin/pylsp --help
```

В PowerShell:

```powershell
py -3.12 -m venv C:\Tools\pylsp
C:\Tools\pylsp\Scripts\python.exe -m pip install -r client/requirements-lsp.txt
C:\Tools\pylsp\Scripts\pylsp.exe --help
```

LSP работает локально через stdio; приложение не устанавливает и не запускает
конфигурации из workspace автоматически. Отдельный процесс может читать проект
и его конфигурацию: используйте только доверенный workspace. Буферы вывода ограничены,
запросы имеют ID, таймаут, отмену и shutdown. Сетевой LSP не поддерживается.

Укажите внешний сервер явно: `export GEMINI_CLI_PYLSP=/opt/example/pylsp/bin/pylsp`
или `$env:GEMINI_CLI_PYLSP='C:\Tools\pylsp\Scripts\pylsp.exe'`.
Попросите модель вызвать `python_lsp` с `action=definition` или `references`,
`filepath=src/app.py`, `line=10`, `character=4`. Строки с единицы, колонки UTF-16 с нуля.
Работа идёт по сохранённым файлам, максимум 200 Python-файлов / 4 МиБ;
несохранённый редакторный буфер не учитывается. При передаче `expected_sha256`
несовпадение версии запрещает запрос. Внешние URI и файлы без снимка отбрасываются;
результат помечен LSP, обычный текстовый поиск не считается точными ссылками.

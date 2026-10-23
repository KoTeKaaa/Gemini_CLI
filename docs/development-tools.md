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

"""Общие определения инструментов без серверных зависимостей."""

from typing import List


def read_local_files(filepaths: List[str]) -> str:
    """
    Reads the content of multiple text-based files (source code, text, configs, logs) from the workspace at once.
    ALWAYS use this when the user asks to fix, refactor, or analyze code across multiple files.

    Args:
        filepaths: A list of RELATIVE file paths starting from the current workspace root.
                   Do NOT use absolute paths. Example: ["main.py", "utils/helpers.py"]
    """
    return "Пакетное чтение файлов инициировано"


def write_local_files(files: List[dict]) -> str:
    """
    Creates or completely overwrites multiple text files in the workspace simultaneously.
    Use this to save generated source code, laboratory scripts, or Markdown documentation.

    CRITICAL: You must provide the FULL and COMPLETE content of the files. Do NOT truncate
    the code with placeholders like '// ... rest of code ...'. Write everything from scratch.

    Args:
        files: A list of dictionaries. Each dict MUST strictly contain:
               - 'filepath' (str): The relative path to the file from workspace root (e.g., 'src/app.py').
               - 'content' (str): The exact and complete text/code content to be written.
    """
    return "Пакетная запись файлов инициирована"


def execute_command(command: str) -> str:
    """
    Executes a SINGLE, NON-INTERACTIVE shell command in the user's terminal workspace (e.g., runs tests, compilers, pip).

    CRITICAL RULES:
    1. Do NOT string multiple commands together using '&&', '||', or ';'. Execute them one by one.
    2. The command MUST be non-interactive. Do NOT run commands that wait for user input (e.g., bare 'python', 'git commit' without -m, 'npm init' without -y).
    3. For Python scripts, use 'python <filename>' or 'python3 <filename>'.

    Args:
        command: The raw shell command string to execute in the workspace.
    """
    return "Выполнение команды инициировано"


LEGACY_NAMES = ("read_local_files", "write_local_files", "execute_command")
TOOLS = {tool.__name__: tool for tool in (read_local_files, write_local_files, execute_command)}


def available_tools(supported: list[str] | None, enabled: set[str] | None = None) -> list:
    requested = set(LEGACY_NAMES if supported is None else supported)
    allowed = set(TOOLS) if enabled is None else enabled
    return [tool for name, tool in TOOLS.items() if name in requested and name in allowed]


def web_search(query: str, max_results: int = 5) -> str:
    """Search the public web for sources. Up to five results; three searches per user turn."""
    return "Поиск инициирован"


TOOLS["web_search"] = web_search
CLIENT_NAMES = (*LEGACY_NAMES, "web_search")


def read_url(url: str) -> str:
    """Read a public HTTP(S) documentation page. Returns actual source URL and bounded text."""
    return "Чтение URL инициировано"


TOOLS["read_url"] = read_url
CLIENT_NAMES = (*CLIENT_NAMES, "read_url")


def find_files(pattern: str = "*") -> str:
    """Find workspace files by relative glob pattern without reading their contents."""
    return "Поиск файлов инициирован"


TOOLS["find_files"] = find_files
CLIENT_NAMES = (*CLIENT_NAMES, "find_files")


def search_text(query: str) -> str:
    """Search literal text in workspace files after user approval; return bounded lines and paths."""
    return "Поиск текста инициирован"


TOOLS["search_text"] = search_text
CLIENT_NAMES = (*CLIENT_NAMES, "search_text")


def read_file_lines(filepath: str, start_line: int, end_line: int) -> str:
    """Read an inclusive range of numbered lines from a workspace text file after approval."""
    return "Чтение диапазона инициировано"


TOOLS["read_file_lines"] = read_file_lines
CLIENT_NAMES = (*CLIENT_NAMES, "read_file_lines")


def replace_in_file(filepath: str, old_text: str, new_text: str) -> str:
    """Replace one unique nonempty literal fragment in an existing text file after a diff approval."""
    return "Точечная замена инициирована"


TOOLS["replace_in_file"] = replace_in_file
CLIENT_NAMES = (*CLIENT_NAMES, "replace_in_file")


def python_symbols(query: str = "") -> str:
    """Read a bounded Python project map of AST definitions/imports after approval; filter names by query."""
    return "Карта Python запрошена"


TOOLS["python_symbols"] = python_symbols
CLIENT_NAMES = (*CLIENT_NAMES, "python_symbols")


def python_lsp(action: str, filepath: str, line: int = 1, character: int = 0,
               expected_sha256: str = "", new_name: str = "") -> str:
    """Query trusted local Python LSP: definition/references/diagnostics/rename. Saved files only.

    line is 1-based, character is 0-based UTF-16. Optional expected_sha256 detects unsaved versions.
    rename requires new_name and a separate file/diff approval. Server configured by user.
    """
    return "LSP запрошен"


TOOLS["python_lsp"] = python_lsp
CLIENT_NAMES = (*CLIENT_NAMES, "python_lsp")


def run_tests(modules: List[str], timeout: int = 120) -> str:
    """Run explicitly selected unittest modules after approval. Empty modules discovers tests/.

    Return structured counts, process exit status and bounded logs; only completed exit 0 can pass.
    """
    return "Запуск unittest запрошен"


TOOLS["run_tests"] = run_tests
CLIENT_NAMES = (*CLIENT_NAMES, "run_tests")

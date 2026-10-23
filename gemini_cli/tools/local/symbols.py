"""Ограниченная карта Python; кэш хранит только символы и импорты."""
import ast
from collections import OrderedDict
from pathlib import Path

from .search import WalkBudget, walk_files
from .workspace import plan_text_file, read_text_snapshot, path_has_links
from ..results import failure, success

_CACHE = OrderedDict()


def project_map(root: str, *, approve, query: str = "", max_files=400) -> dict:
    if not isinstance(query, str) or len(query) > 200:
        return failure("invalid_arguments", "Нужен запрос до 200 символов")
    plans, budget = [], WalkBudget()
    for relative, path in walk_files(root, budget):
        if relative.endswith(".py") and not path_has_links(path):
            if len(plans) >= max_files:
                budget.truncated = True
                break
            try:
                plans.append((relative, plan_text_file(root, relative, max_bytes=262144)))
            except (OSError, ValueError):
                budget.skipped += 1
    if not approve(f"Карта Python: прочитать до {len(plans)} файлов; отправить символы и импорты"):
        return failure("denied", "Чтение проекта отклонено")
    root_key = str(Path(root).resolve())
    cache = _CACHE.setdefault(root_key, {})
    _CACHE.move_to_end(root_key)
    while len(_CACHE) > 4:
        _CACHE.popitem(last=False)
    live, rows, total = set(), [], 0
    for relative, expected in plans:
        live.add(relative)
        total += expected[1][2]
        if total > 4 * 1024 * 1024:
            budget.truncated = True
            break
        try:
            # Validate even a cached entry against the current workspace identity.
            if plan_text_file(root, relative, max_bytes=262144) != expected:
                raise ValueError("Файл изменён")
            if cache.get(relative, (None,))[0] != expected:
                source = read_text_snapshot(root, relative, expected, max_bytes=262144)
                tree = ast.parse(source)
                symbols, imports = [], []
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        symbols.append({"name": node.name, "line": node.lineno,
                                        "kind": "class" if isinstance(node, ast.ClassDef) else "function"})
                    elif isinstance(node, ast.Import):
                        imports.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        imports.append("." * node.level + (node.module or ""))
                cache[relative] = (expected, symbols[:200], imports[:100],
                                   len(symbols) > 200 or len(imports) > 100)
            _, symbols, imports, truncated = cache[relative]
            selected = [s for s in symbols if query.casefold() in s["name"].casefold()]
            if selected or not query:
                rows.append({"path": relative, "symbols": selected, "imports": imports})
            budget.truncated |= truncated
            if sum(len(row["symbols"]) + len(row["imports"]) + 1 for row in rows) >= 500:
                budget.truncated = True
                break
        except (OSError, ValueError, UnicodeError, SyntaxError, RecursionError):
            budget.skipped += 1
            cache.pop(relative, None)
    for stale in set(cache) - live:
        del cache[stale]
    return success({"files": rows, "skipped": budget.skipped,
                    "precision": "Python AST definitions; imports are syntactic"}, truncated=budget.truncated)

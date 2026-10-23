"""Ограниченный обход workspace без следования символическим ссылкам."""

import fnmatch
import os
from dataclasses import dataclass

from ..results import failure, success
from .workspace import is_sensitive_read_path, resolve_safe_path, plan_text_file, read_text_snapshot

SKIP_DIRS = {".git", ".venv", ".venv-win", "venv", "node_modules", "__pycache__", "build", "dist"}


@dataclass
class WalkBudget:
    limit: int = 10000
    visited: int = 0
    truncated: bool = False
    skipped: int = 0


def walk_files(root: str, budget: WalkBudget):
    root = os.path.realpath(root)
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if budget.visited >= budget.limit:
                        budget.truncated = True
                        return
                    budget.visited += 1
                    if entry.is_symlink():
                        continue
                    path = resolve_safe_path(root, entry.path)
                    if path is None or is_sensitive_read_path(path):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                            stack.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        yield os.path.relpath(path, root).replace(os.sep, "/"), path
        except OSError:
            budget.skipped += 1
            budget.truncated = True


def find_files(args: dict, current_dir: str, *, max_entries=10000, max_results=200) -> dict:
    pattern = args.get("pattern", "*")
    if (not isinstance(pattern, str) or not pattern or len(pattern) > 500
            or os.path.isabs(pattern) or ".." in pattern.replace("\\", "/").split("/")):
        return failure("invalid_arguments", "Нужна относительная маска без выхода из workspace")
    budget, matches = WalkBudget(max_entries), []
    for relative, path in walk_files(current_dir, budget):
        if fnmatch.fnmatchcase(relative, pattern) or fnmatch.fnmatchcase(os.path.basename(path), pattern):
            if len(matches) >= max_results:
                budget.truncated = True
                break
            matches.append(relative)
    return success({"paths": matches, "skipped": budget.skipped}, truncated=budget.truncated)


def search_text(args: dict, current_dir: str, *, approve, max_results=200, max_chars=20000) -> dict:
    query = args.get("query")
    if not isinstance(query, str) or not query or len(query) > 2000:
        return failure("invalid_arguments", "Нужна непустая строка поиска до 2000 символов")
    budget, plans = WalkBudget(), []
    for relative, path in walk_files(current_dir, budget):
        try:
            plans.append((relative, plan_text_file(current_dir, relative)))
        except (OSError, ValueError):
            budget.skipped += 1
    if not approve(f"Поиск текста в {len(plans)} файлах workspace; совпадения будут отправлены модели"):
        return failure("denied", "Поиск содержимого отклонён пользователем")
    matches, characters, read_bytes = [], 0, 0
    for relative, expected in plans:
        read_bytes += expected[1][2]
        if read_bytes > 8 * 1024 * 1024:
            budget.truncated = True
            break
        try:
            text = read_text_snapshot(current_dir, relative, expected)
        except (OSError, ValueError, UnicodeError):
            budget.skipped += 1
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if query in line:
                position = line.index(query)
                snippet = line[max(0, position - 100):position + min(len(query), 200) + 100]
                if len(matches) >= max_results or characters + len(snippet) > max_chars:
                    return success({"matches": matches, "skipped": budget.skipped}, truncated=True)
                matches.append({"path": relative, "line": number, "text": snippet})
                characters += len(snippet)
                budget.truncated |= len(snippet) < len(line)
    return success({"matches": matches, "skipped": budget.skipped}, truncated=budget.truncated)

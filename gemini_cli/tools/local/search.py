"""Ограниченный обход workspace без следования символическим ссылкам."""

import fnmatch
import os
from dataclasses import dataclass

from ..results import failure, success
from .workspace import is_sensitive_read_path, resolve_safe_path

SKIP_DIRS = {".git", ".venv", ".venv-win", "venv", "node_modules", "__pycache__", "build", "dist"}


@dataclass
class WalkBudget:
    limit: int = 10000
    visited: int = 0
    truncated: bool = False
    skipped: int = 0


def walk_files(root: str, budget: WalkBudget):
    stack = [os.path.realpath(root)]
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

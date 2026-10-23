"""Рекомендации по явным импортам; отсутствие ребра не доказывает отсутствие влияния."""
import ast
from pathlib import PurePosixPath
from importlib.util import resolve_name

from .lsp_tools import documents, validate_versions
from ..results import failure, success


def module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix('').parts)
    return '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)


def affected_tests(args: dict, root: str, *, approve) -> dict:
    files = args.get('files')
    if (not isinstance(files, list) or not 1 <= len(files) <= 64
            or any(not isinstance(path, str) or not path or path.startswith(('/', '\\'))
                   or '\\' in path or '..' in PurePosixPath(path).parts for path in files)):
        return failure('invalid_arguments', 'Нужен явный список 1–64 относительных изменённых файлов')
    if not approve('Прочитать импорты Python для рекомендаций тестов по выбранным файлам'):
        return failure('denied', 'Чтение импортов отклонено')
    try:
        docs = documents(root)
        modules = {module_name(path): path for path in docs}
        graph, uncertain = {}, []
        for module, path in modules.items():
            package = module if path.endswith('/__init__.py') else module.rpartition('.')[0]
            imports = set()
            try:
                tree = ast.parse(docs[path][1])
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.update(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        name = '.' * node.level + (node.module or '')
                        base = resolve_name(name, package) if node.level else name
                        imports.add(base)
                        imports.update(base + '.' + alias.name for alias in node.names)
                    elif isinstance(node, ast.Call) and ((isinstance(node.func, ast.Name)
                            and node.func.id in {'__import__', 'eval', 'exec'}) or
                            (isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module')):
                        uncertain.append(path + ': динамическая зависимость')
            except (SyntaxError, ValueError, ImportError, RecursionError):
                uncertain.append(path + ': импорты разобраны не полностью')
            graph[module] = {name for name in modules if any(
                imported == name or imported.startswith(name + '.') for imported in imports)}
        changed = {module_name(path) for path in files if path.endswith('.py')}
        unknown = [path for path in files if not path.endswith('.py') or path not in docs]
        affected = set(changed)
        while True:
            added = {name for name, deps in graph.items() if deps & affected} - affected
            if not added:
                break
            affected.update(added)
        tests = sorted(name for name in affected if name in modules
                       and PurePosixPath(modules[name]).name.startswith('test_'))
        validate_versions(root, docs)
        return success({'selected_files': files, 'suggested_modules': tests,
            'basis': 'Прямые и транзитивные явные Python-импорты',
            'uncertainty': (uncertain + [path + ': изменение вне известного графа' for path in unknown])[:100],
            'complete': False, 'fallback': 'Полная регрессия нужна: граф не учитывает данные, плагины и внешние вызовы'},
            truncated=len(uncertain) + len(unknown) > 100)
    except (OSError, ValueError, UnicodeError):
        return failure('incomplete_graph', 'Граф неполон; выполните полную регрессию')

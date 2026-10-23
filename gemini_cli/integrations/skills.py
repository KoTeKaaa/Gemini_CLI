"""Явный локальный каталог Agent Skills; обнаружение не загружает тело."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat

import yaml

from ..tools.local.workspace import path_has_links, is_sensitive_read_path, file_identity

MAX_FILE = 65536
MAX_HEADER = 8192
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def checked_path(root: Path, relative: str) -> Path:
    parts = relative.replace('\\', '/').split('/')
    if (not relative or any(p in {'', '.', '..'} or p.startswith('.') or ':' in p for p in parts)
            or Path(relative).is_absolute()):
        raise ValueError("Нужен относительный путь внутри навыка")
    path = root.joinpath(*parts)
    if path_has_links(str(path)) or is_sensitive_read_path(str(path)):
        raise ValueError("Ссылки и секретные файлы недоступны")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Выход за каталог навыка")
    return path


def read_file(root: Path, relative: str, *, header_only=False) -> str:
    path = checked_path(root, relative)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
        raise ValueError("Нужен обычный файл до 64 КиБ")
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (not os.path.samestat(info, opened) or info.st_size != opened.st_size
                or info.st_mtime_ns != opened.st_mtime_ns or not stat.S_ISREG(opened.st_mode)):
            raise ValueError("Файл изменился при открытии")
        if header_only:
            data = stream.readline(MAX_HEADER + 1)
            if data.rstrip(b'\r\n') != b'---':
                raise ValueError("Отсутствует YAML frontmatter")
            while len(data) <= MAX_HEADER:
                line = stream.readline(MAX_HEADER + 1 - len(data))
                data += line
                if line.rstrip(b'\r\n') == b'---':
                    break
                if not line:
                    raise ValueError("Не закрыт YAML frontmatter")
            else:
                raise ValueError("Frontmatter превышает 8 КиБ")
        else:
            data = stream.read(MAX_FILE + 1)
        if (len(data) > MAX_FILE or file_identity(os.fstat(stream.fileno())) != file_identity(opened)
                or path_has_links(str(path)) or not os.path.samestat(path.stat(), opened)):
            raise ValueError("Файл изменился во время чтения")
    if b'\x00' in data:
        raise ValueError("Нужен текст UTF-8")
    return data.decode('utf-8')


def metadata(text: str, directory: str) -> dict:
    lines = text.splitlines()
    if not lines or lines[0] != '---' or '---' not in lines[1:]:
        raise ValueError("Неверный frontmatter")
    header = '\n'.join(lines[1:lines.index('---', 1)])
    if len(header.encode()) > MAX_HEADER:
        raise ValueError("Frontmatter превышает 8 КиБ")
    try:
        if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken, yaml.tokens.TagToken))
               for token in yaml.scan(header)):
            raise ValueError("YAML aliases и tags не поддерживаются")
        node = yaml.compose(header, Loader=yaml.BaseLoader)
        if not isinstance(node, yaml.MappingNode):
            raise ValueError("Frontmatter должен быть mapping")
        keys = [key.value for key, _ in node.value if isinstance(key, yaml.ScalarNode)]
        if len(keys) != len(node.value) or len(set(keys)) != len(keys):
            raise ValueError("Повторные или сложные YAML keys")
        row = yaml.load(header, Loader=yaml.BaseLoader)
    except (yaml.YAMLError, RecursionError):
        raise ValueError("Неверный YAML frontmatter") from None
    name, description = row.get('name'), row.get('description')
    if (not isinstance(name, str) or len(name) > 64 or not NAME.fullmatch(name)
            or name != directory or not isinstance(description, str) or not description.strip()
            or len(description) > 1024):
        raise ValueError("Неверные name/description или имя каталога")
    for field, limit in (('license', 1024), ('compatibility', 500), ('allowed-tools', 4096)):
        if field in row and (not isinstance(row[field], str) or not 1 <= len(row[field]) <= limit):
            raise ValueError("Неверное необязательное поле")
    if 'metadata' in row and (not isinstance(row['metadata'], dict) or
            any(not isinstance(v, str) for v in row['metadata'].values())):
        raise ValueError("metadata должен содержать строки")
    return row


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    root: Path

    def load(self) -> str:
        text = read_file(self.root, 'SKILL.md')
        metadata(text, self.name)
        return text


def catalog(config: Path) -> tuple[dict[str, Skill], list[str]]:
    if not config.exists():
        return {}, []
    row = json.loads(read_file(config.parent, config.name))
    roots = row.get('directories') if isinstance(row, dict) and row.get('version') == 1 else None
    if (not isinstance(roots, list) or len(roots) > 16 or
            any(not isinstance(p, str) or not Path(p).is_absolute() for p in roots)):
        raise ValueError("skills.json: нужны version=1 и абсолютные directories (до 16)")
    found, errors, duplicates = {}, [], set()
    for configured in dict.fromkeys(roots):
        root = Path(configured)
        if path_has_links(str(root)):
            errors.append('Каталог со ссылками пропущен')
            continue
        try:
            with os.scandir(root) as entries:
                for count, entry in enumerate(entries):
                    if count >= 256:
                        errors.append('Предел: 256 записей на каталог')
                        break
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    try:
                        skill_root = root / entry.name
                        row = metadata(read_file(skill_root, 'SKILL.md', header_only=True), entry.name)
                        name = row['name']
                        if name in found or name in duplicates:
                            found.pop(name, None)
                            duplicates.add(name)
                            errors.append(f'Дубликат навыка: {name}')
                        else:
                            found[name] = Skill(name, row['description'], skill_root)
                    except (ValueError, OSError, UnicodeError):
                        errors.append('Навык пропущен: неверный или недоступный SKILL.md')
        except OSError:
            errors.append('Настроенный каталог недоступен')
    return found, errors

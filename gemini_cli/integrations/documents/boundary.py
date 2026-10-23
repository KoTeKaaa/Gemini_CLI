"""Проверка формата, контейнера и пределов до извлечения текста."""
import io
import json
from pathlib import PurePosixPath
import zipfile

MAX_BYTES = 4 * 1024 * 1024
MAX_EXPANDED = 16 * 1024 * 1024
MAX_MEMBER = 4 * 1024 * 1024
MAX_OUTPUT = 6000
MIMES = {'.pdf': 'application/pdf', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
         '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.csv': 'text/csv'}


class DocumentError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def xml(data: bytes):
    from defusedxml.ElementTree import fromstring
    return fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)


class Package:
    def __init__(self, data: bytes):
        self.archive = zipfile.ZipFile(io.BytesIO(data))
        entries = self.archive.infolist()
        seen, total = set(), 0
        for item in entries:
            name = item.filename
            total += item.file_size
            if (name in seen or name.startswith('/') or '\\' in name or '..' in PurePosixPath(name).parts
                    or item.flag_bits & 1 or item.file_size > MAX_MEMBER or item.compress_type not in (0, 8)
                    or item.file_size > max(1, item.compress_size) * 100
                    or 'vbaproject' in name.casefold() or name.casefold().endswith(('.bin', '.exe'))):
                raise DocumentError('unsupported', 'Неподдерживаемый, зашифрованный или опасный ZIP-контейнер')
            seen.add(name)
        if len(entries) > 1000 or total > MAX_EXPANDED:
            raise DocumentError('limit', 'Превышен предел распаковки документа')
        self.names = seen
        for name in seen:
            if name.endswith('.rels'):
                relationships = self.tree(name)
                if any(node.get('TargetMode', '').casefold() == 'external' for node in relationships.iter()):
                    raise DocumentError('unsupported', 'Внешние связи документа не поддерживаются')

    def read(self, name: str) -> bytes:
        info = self.archive.getinfo(name)
        if info.file_size > MAX_MEMBER:
            raise DocumentError('limit', 'Слишком большая XML-часть')
        with self.archive.open(info) as stream:
            data = stream.read(MAX_MEMBER + 1)
        if len(data) > MAX_MEMBER:
            raise DocumentError('limit', 'Слишком большая XML-часть')
        return data

    def tree(self, name: str):
        return xml(self.read(name))


def inspect(data: bytes, extension: str, mime: str = '') -> Package | None:
    if extension not in MIMES or mime and mime != MIMES[extension]:
        raise DocumentError('unsupported', 'Расширение или MIME документа не поддерживается')
    if not data or len(data) > MAX_BYTES:
        raise DocumentError('limit', 'Документ должен быть непустым и не больше 4 МиБ')
    if extension == '.pdf':
        if not data.startswith(b'%PDF-'):
            raise DocumentError('invalid_document', 'Содержимое не соответствует PDF')
    elif extension in {'.docx', '.xlsx'}:
        if not data.startswith(b'PK\x03\x04'):
            raise DocumentError('invalid_document', 'Содержимое не соответствует OOXML')
        package = Package(data)
        required = 'word/document.xml' if extension == '.docx' else 'xl/workbook.xml'
        if required not in package.names or '[Content_Types].xml' not in package.names:
            raise DocumentError('invalid_document', 'Неверный тип OOXML-контейнера')
        types = package.tree('[Content_Types].xml')
        if any('macroenabled' in node.get('ContentType', '').casefold() for node in types.iter()):
            raise DocumentError('unsupported', 'Макросы не поддерживаются')
        return package
    return None


def numbers(value: str, *, maximum: int, count=10) -> range:
    if not isinstance(value, str):
        raise DocumentError('invalid_selection', 'Нужен диапазон с единицы, например 1-3')
    parts = value.split('-')
    if len(parts) > 2 or any(not part.isascii() or not part.isdigit() or len(part) > 7 for part in parts):
        raise DocumentError('invalid_selection', 'Неверный диапазон')
    start, end = int(parts[0]), int(parts[-1])
    if not 1 <= start <= end <= maximum or end - start >= count:
        raise DocumentError('invalid_selection', 'Диапазон вне документа или превышает предел')
    return range(start, end + 1)


def result(source: str, fragments: list[dict], *, partial=False, truncated=False, notes=None) -> dict:
    rows, used = [], 0
    for row in fragments:
        size = len(json.dumps(row, ensure_ascii=False).encode('utf-8'))
        if used + size > MAX_OUTPUT:
            truncated = True
            remaining = MAX_OUTPUT - used - 300
            if remaining > 500:
                clipped = dict(row)
                if 'text' in clipped:
                    clipped['text'] = clipped['text'].encode('utf-8')[:remaining].decode('utf-8', errors='ignore')
                elif 'cells' in clipped:
                    clipped['cells'] = []
                    for value in row['cells']:
                        if isinstance(value, dict):
                            value = {k: v.encode('utf-8')[:800].decode('utf-8', errors='ignore')
                                     if isinstance(v, str) else v for k, v in value.items()}
                        elif isinstance(value, str):
                            value = value.encode('utf-8')[:800].decode('utf-8', errors='ignore')
                        candidate = {**clipped, 'cells': [*clipped['cells'], value], 'truncated': True}
                        if len(json.dumps(candidate, ensure_ascii=False).encode('utf-8')) > remaining: break
                        clipped = candidate
                clipped['truncated'] = True
                if len(json.dumps(clipped, ensure_ascii=False).encode('utf-8')) <= MAX_OUTPUT - used:
                    rows.append(clipped)
            break
        used += size
        rows.append(row)
    output = {'status': 'ok', 'source': source, 'fragments': rows, 'partial': partial or truncated,
              'truncated': truncated, 'notes': notes or []}
    # Match the shared runner's JSON-string wire budget, including Unicode escapes.
    while len(json.dumps(json.dumps(output, ensure_ascii=False)).encode('utf-8')) > 7800 and rows:
        last = dict(rows[-1])
        if isinstance(last.get('text'), str) and len(last['text']) > 200:
            last['text'] = last['text'][:len(last['text']) // 2]
        elif len(last.get('cells', [])) > 1:
            last['cells'] = last['cells'][:len(last['cells']) // 2]
        else:
            rows.pop()
            output.update(partial=True, truncated=True)
            continue
        rows[-1] = {**last, 'truncated': True}
        output.update(partial=True, truncated=True)
    return output

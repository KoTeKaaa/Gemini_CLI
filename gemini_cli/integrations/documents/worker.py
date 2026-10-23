"""Один запрос через память stdin/stdout; никаких файлов, сети и пользовательских скриптов."""
import base64
import json
import os
import sys
from .boundary import DocumentError, MAX_BYTES, inspect


def extract(data: bytes, source: str, selection: dict, mime='') -> dict:
    from pathlib import PurePosixPath
    extension = PurePosixPath(source).suffix.casefold()
    try:
        package = inspect(data, extension, mime)
        if extension == '.pdf':
            from .pdf import parse
        elif extension == '.docx':
            from .docx import parse
        elif extension == '.csv':
            from .csv import parse
        else:
            from .xlsx import parse
        return parse(data if package is None else package, source, selection)
    except ImportError:
        return {'status': 'error', 'error': {'code': 'dependency_missing', 'message': 'Не установлен локальный парсер документа'}}
    except DocumentError as error:
        return {'status': 'error', 'error': {'code': error.code, 'message': str(error)}}
    except (MemoryError, RecursionError):
        return {'status': 'error', 'error': {'code': 'limit', 'message': 'Превышен ресурсный предел документа'}}
    except Exception:
        return {'status': 'error', 'error': {'code': 'invalid_document', 'message': 'Документ повреждён или формат не поддерживается'}}


def main() -> None:
    if os.name == 'posix':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    try:
        raw = sys.stdin.buffer.readline(MAX_BYTES * 4 // 3 + 16384)
        request = json.loads(raw)
        data = base64.b64decode(request['bytes'], validate=True)
        if len(data) > MAX_BYTES or not isinstance(request['selection'], dict):
            raise ValueError()
        response = extract(data, request['source'], request['selection'], request.get('mime', ''))
    except Exception:
        response = {'status': 'error', 'error': {'code': 'invalid_request', 'message': 'Неверный запрос парсера'}}
    sys.stdout.buffer.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))
    sys.stdout.buffer.flush()


if __name__ == '__main__':
    main()

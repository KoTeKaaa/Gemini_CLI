"""JSON-совместимые результаты новых инструментов; старые форматы сохраняются."""


def success(data: dict, *, truncated: bool = False) -> dict:
    return {"status": "ok", "data": data, "truncated": truncated}


def failure(code: str, message: str) -> dict:
    return {"status": "error", "error": {"code": code, "message": message}}

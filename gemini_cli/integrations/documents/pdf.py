"""Только выбранные PDF-страницы; изображения/OCR/JavaScript не исполняются."""
import io
from .boundary import DocumentError, numbers, result


def parse(data: bytes, source: str, selection: dict) -> dict:
    if set(selection) != {'pages'}:
        raise DocumentError('invalid_selection', 'PDF: укажите pages=1-3 (до 10 страниц)')
    from pypdf import PdfReader, apply_configuration
    # Bound each decompressed stream; the process has a separate memory/time cap.
    with apply_configuration(zlib_maximum_output_length=4 * 1024 * 1024,
                             lzw_maximum_output_length=4 * 1024 * 1024,
                             run_length_maximum_output_length=4 * 1024 * 1024,
                             jbig2dec_binary=None):
        return pages(PdfReader(io.BytesIO(data), strict=True), source, selection)


def pages(reader, source: str, selection: dict) -> dict:
    if reader.is_encrypted:
        raise DocumentError('unsupported', 'Зашифрованный PDF не поддерживается')
    count = len(reader.pages)
    if count > 2000:
        raise DocumentError('limit', 'PDF превышает 2000 страниц')
    selected = numbers(selection['pages'], maximum=count)
    fragments, found_text = [], False
    for page_number in selected:
        page = reader.pages[page_number - 1]
        contents = page.get_contents()
        if contents is not None and len(contents.get_data()) > 4 * 1024 * 1024:
            raise DocumentError('limit', 'Поток страницы слишком большой')
        text = page.extract_text() or ''
        found_text |= bool(text.strip())
        fragments.append({'position': {'page': page_number}, 'text': text[:20000],
                          'status': 'text' if text.strip() else 'no_text', 'truncated': len(text) > 20000})
    if not found_text:
        raise DocumentError('unsupported', 'На выбранных страницах нет извлекаемого текста; возможен скан. OCR не выполняется')
    return result(source, fragments, partial=True, truncated=any(r['truncated'] for r in fragments),
                  notes=['Текстовое извлечение не гарантирует порядок и полноту визуального содержимого PDF'])

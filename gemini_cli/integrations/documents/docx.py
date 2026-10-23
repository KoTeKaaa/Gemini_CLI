"""Абзацы, Word-секции sectPr и таблицы в порядке document.xml."""
from .boundary import DocumentError, numbers, result

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def content(node) -> str:
    values = []
    for part in node.iter():
        if part.tag == W + 't': values.append(part.text or '')
        elif part.tag == W + 'tab': values.append('\t')
        elif part.tag == W + 'br': values.append('\n')
    return ''.join(values)


def parse(package, source: str, selection: dict) -> dict:
    if len(selection) != 1 or not set(selection) <= {'paragraphs', 'sections', 'tables'}:
        raise DocumentError('invalid_selection', 'DOCX: выберите paragraphs=1-5, sections=1 или tables=1')
    body = package.tree('word/document.xml').find(W + 'body')
    if body is None:
        raise DocumentError('invalid_document', 'В DOCX отсутствует document/body')
    paragraphs, tables, section, records = 0, 0, 1, []
    for node in body:
        if node.tag == W + 'p':
            paragraphs += 1
            records.append({'position': {'paragraph': paragraphs, 'section': section}, 'text': content(node)})
            if node.find('.//' + W + 'sectPr') is not None:
                section += 1
        elif node.tag == W + 'tbl':
            tables += 1
            for row_id, row in enumerate(node.findall(W + 'tr'), 1):
                values = [content(cell) for cell in row.findall(W + 'tc')]
                records.append({'position': {'table': tables, 'row': row_id, 'section': section}, 'cells': values})
        if len(records) > 20000:
            raise DocumentError('limit', 'Слишком много элементов DOCX')
    key = next(iter(selection))
    field = {'paragraphs': 'paragraph', 'sections': 'section', 'tables': 'table'}[key]
    maximum = {'paragraphs': paragraphs, 'sections': section, 'tables': tables}[key]
    chosen = numbers(selection[key], maximum=maximum, count=20)
    fragments = [row for row in records if row['position'].get(field) in chosen]
    return result(source, fragments, partial=True,
                  notes=['Только основной текст/таблицы. Секции — границы Word sectPr; колонтитулы, сноски, рисунки и разметка не извлекаются'])

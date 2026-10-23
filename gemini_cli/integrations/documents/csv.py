"""CSV: явная кодировка и ограниченный диапазон, без исполнения формул."""
import csv
import io
from .boundary import DocumentError, result
from .grid import rectangle, column_name


def parse(data: bytes, source: str, selection: dict) -> dict:
    if 'cells' not in selection or set(selection) - {'cells', 'encoding', 'delimiter'}:
        raise DocumentError('invalid_selection', 'CSV: cells=A1:C10, encoding=utf-8-sig, delimiter=;')
    encoding = selection.get('encoding', 'utf-8-sig')
    if encoding not in {'utf-8-sig', 'utf-8', 'utf-16', 'cp1251'}:
        raise DocumentError('invalid_selection', 'Кодировка: utf-8-sig/utf-8/utf-16/cp1251')
    text = data.decode(encoding)
    delimiter = selection.get('delimiter')
    if delimiter is None:
        try: delimiter = csv.Sniffer().sniff(text[:4096], delimiters=',;\t|').delimiter
        except csv.Error: delimiter = ','
    if delimiter not in {',', ';', '\t', '|'}:
        raise DocumentError('invalid_selection', 'Разделитель: запятая, точка с запятой, tab или |')
    start_row, start_col, end_row, end_col = rectangle(selection['cells'])
    fragments, visited = [], 0
    for row_id, row in enumerate(csv.reader(io.StringIO(text, newline=''), delimiter=delimiter), 1):
        visited = row_id
        if row_id > end_row: break
        if row_id >= start_row:
            values = [{'cell': column_name(col) + str(row_id),
                       'value': row[col - 1] if col <= len(row) else None}
                      for col in range(start_col, end_col + 1)]
            fragments.append({'position': {'row': row_id}, 'cells': values})
    if start_row > visited:
        raise DocumentError('invalid_selection', 'Диапазон начинается после конца CSV')
    return result(source, fragments, partial=visited < end_row,
                  notes=['Кодировка: ' + encoding, 'Столбцы: ' + ', '.join(column_name(c) for c in range(start_col, end_col + 1)),
                         'Заголовки включаются только если выбран их ряд. Формулы CSV остаются буквальным текстом'])

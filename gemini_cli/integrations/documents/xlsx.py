"""OOXML cells: формула и сохранённое значение читаются отдельно без пересчёта."""
import posixpath
from .boundary import DocumentError, result
from .grid import rectangle, cell, column_name

S = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def strings(node) -> str:
    return ''.join(part.text or '' for part in node.iter(S + 't'))


def parse(package, source: str, selection: dict) -> dict:
    sheets = package.tree('xl/workbook.xml').findall('./' + S + 'sheets/' + S + 'sheet')
    if selection == {'sheets': 'list'}:
        return result(source, [{'position': {'sheet_index': i}, 'name': node.get('name', '')}
                               for i, node in enumerate(sheets[:50], 1)], truncated=len(sheets) > 50)
    if set(selection) != {'sheet', 'cells'} or not isinstance(selection['sheet'], str):
        raise DocumentError('invalid_selection', 'XLSX: sheet=Лист1&cells=A1:C10; список: sheets=list')
    start_row, start_col, end_row, end_col = rectangle(selection['cells'])
    chosen = [node for node in sheets if node.get('name') == selection['sheet']]
    if len(chosen) != 1:
        raise DocumentError('invalid_selection', 'Лист не найден или неоднозначен; запросите sheets=list')
    rel_id = chosen[0].get(R + 'id')
    relations = package.tree('xl/_rels/workbook.xml.rels')
    links = [node for node in relations if node.get('Id') == rel_id]
    if len(links) != 1 or not links[0].get('Type', '').endswith('/worksheet'):
        raise DocumentError('unsupported', 'Неизвестный тип листа')
    target = links[0].get('Target', '')
    if target.startswith('/'):
        target = target.lstrip('/')
    else:
        target = posixpath.normpath(posixpath.join('xl', target))
    if not target.startswith('xl/worksheets/') or '..' in target.split('/') or target not in package.names:
        raise DocumentError('unsupported', 'Недопустимый путь листа')
    shared = []
    if 'xl/sharedStrings.xml' in package.names:
        shared = [strings(node) for node in package.tree('xl/sharedStrings.xml').findall(S + 'si')]
        if len(shared) > 100000:
            raise DocumentError('limit', 'Слишком много общих строк XLSX')
    sheet = package.tree(target)
    values, incomplete = {}, False
    for element in sheet.findall('./' + S + 'sheetData/' + S + 'row/' + S + 'c'):
        row, col = cell(element.get('r', ''))
        if not (start_row <= row <= end_row and start_col <= col <= end_col): continue
        reference = column_name(col) + str(row)
        if reference in values:
            raise DocumentError('invalid_document', 'Повторная ячейка XLSX')
        kind = element.get('t', 'n')
        saved = element.find(S + 'v')
        value = saved.text if saved is not None else None
        if kind == 's' and value is not None:
            index = int(value)
            if not 0 <= index < len(shared): raise DocumentError('invalid_document', 'Неверная shared string')
            value = shared[index]
        elif kind == 'inlineStr': value = strings(element)
        formula = element.find(S + 'f')
        record = {'cell': reference, 'type': kind, 'value': value}
        if formula is not None:
            record.update({'formula': formula.text or '', 'formula_attributes': dict(formula.attrib),
                           'cached_value_missing': value is None})
            incomplete |= value is None
        values[reference] = record
    rows = []
    for row in range(start_row, end_row + 1):
        records = []
        for col in range(start_col, end_col + 1):
            name = column_name(col) + str(row)
            records.append(values.get(name, {'cell': name, 'value': None, 'type': 'empty'}))
        rows.append({'position': {'sheet': selection['sheet'], 'row': row}, 'cells': records})
    return result(source, rows, partial=incomplete,
                  notes=['Формулы не пересчитываются. value — сырой сохранённый XML-кэш, не форматированное отображение Excel.',
                         'Заголовки включаются только в выбранных строках. Пустое/отсутствующее значение — null.'])

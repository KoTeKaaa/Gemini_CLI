"""Ограниченный Excel A1-диапазон для табличных документов."""
import re
from .boundary import DocumentError


def column_name(number: int) -> str:
    result = ''
    while number:
        number, digit = divmod(number - 1, 26)
        result = chr(65 + digit) + result
    return result


def cell(value: str) -> tuple[int, int]:
    match = re.fullmatch(r'([A-Za-z]{1,3})([1-9][0-9]{0,6})', value)
    if not match:
        raise DocumentError('invalid_selection', 'Нужна ячейка A1')
    column = 0
    for char in match[1].upper(): column = column * 26 + ord(char) - 64
    row = int(match[2])
    if column > 16384 or row > 1048576:
        raise DocumentError('invalid_selection', 'Ячейка за пределами Excel')
    return row, column


def rectangle(value: str) -> tuple[int, int, int, int]:
    if not isinstance(value, str) or value.count(':') > 1:
        raise DocumentError('invalid_selection', 'Нужен диапазон cells=A1:C10')
    ends = value.split(':')
    first_row, first_col = cell(ends[0])
    last_row, last_col = cell(ends[-1])
    if (last_row < first_row or last_col < first_col or last_row - first_row >= 100
            or (last_row - first_row + 1) * (last_col - first_col + 1) > 200):
        raise DocumentError('invalid_selection', 'Обратный диапазон или больше 100 строк/200 ячеек')
    return first_row, first_col, last_row, last_col

import unittest
from gemini_cli.integrations.documents.worker import extract
from gemini_cli.integrations.documents.client import extract_document
from tests.test_document_boundary import archive

S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def workbook(empty=False):
    rows = '' if empty else '''<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>Значение</t></is></c></row>
    <row r="2"><c r="A2"><f>1+2</f><v>3</v></c><c r="B2"><f>NOW()</f></c><c r="C2" t="inlineStr"><is><t>PRIVATE</t></is></c></row>'''
    return archive({'[Content_Types].xml': '<Types/>',
        'xl/workbook.xml': f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets><sheet name="Данные" sheetId="1" r:id="r1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': f'<Relationships><Relationship Id="r1" Type="{R}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': f'<worksheet xmlns="{S}"><sheetData>{rows}</sheetData></worksheet>',
        'xl/sharedStrings.xml': f'<sst xmlns="{S}"><si><t>Имя</t></si></sst>'})


class DocumentXLSXTests(unittest.TestCase):
    def test_formula_cache_unicode_selected_cells_and_worker(self):
        result = extract_document(workbook(), 'a.xlsx', {'sheet': 'Данные', 'cells': 'A1:B2'})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['fragments'][0]['cells'][0]['value'], 'Имя')
        formulas = result['fragments'][1]['cells']
        self.assertEqual(formulas[0]['formula'], '1+2')
        self.assertEqual(formulas[0]['value'], '3')
        self.assertTrue(formulas[1]['cached_value_missing'])
        self.assertTrue(result['partial'])
        self.assertNotIn('PRIVATE', str(result))
        self.assertEqual(extract(workbook(), 'a.xlsx', {'sheets': 'list'})['fragments'][0]['name'], 'Данные')

    def test_empty_sheet_unknown_sheet_and_range_limits(self):
        result = extract(workbook(True), 'a.xlsx', {'sheet': 'Данные', 'cells': 'A1:B1'})
        self.assertTrue(all(item['value'] is None for item in result['fragments'][0]['cells']))
        for selection in ({'sheet': 'unknown', 'cells': 'A1'}, {'sheet': 'Данные', 'cells': 'A1:ZZ100'}):
            self.assertEqual(extract(workbook(), 'a.xlsx', selection)['error']['code'], 'invalid_selection')

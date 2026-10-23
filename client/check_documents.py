"""Автономный offline smoke документного worker в готовой сборке, только stdlib."""
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def archive(parts):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as value:
        for name, text in parts.items(): value.writestr(name, text)
    return stream.getvalue()


def pdf():
    content = b'BT /F1 12 Tf 10 100 Td (PACKAGED_PDF) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream']
    data, offsets = b'%PDF-1.4\n', [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(data)); data += f'{index} 0 obj\n'.encode() + value + b'\nendobj\n'
    start = len(data)
    data += b'xref\n0 6\n0000000000 65535 f \n'
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return data + f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


def check(executable: Path):
    w = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    s = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    r = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    docx = archive({'[Content_Types].xml': '<Types/>', 'word/document.xml':
        f'<w:document xmlns:w="{w}"><w:body><w:p><w:r><w:t>PACKAGED_DOCX</w:t></w:r></w:p></w:body></w:document>'})
    xlsx = archive({'[Content_Types].xml': '<Types/>', 'xl/workbook.xml':
        f'<workbook xmlns="{s}" xmlns:r="{r}"><sheets><sheet name="Data" r:id="r1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': f'<Relationships><Relationship Id="r1" Type="{r}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': f'<worksheet xmlns="{s}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>PACKAGED_XLSX</t></is></c></row></sheetData></worksheet>'})
    fixtures = [('a.pdf', pdf(), {'pages': '1'}, 'PACKAGED_PDF'),
                ('a.docx', docx, {'paragraphs': '1'}, 'PACKAGED_DOCX'),
                ('a.csv', b'PACKAGED_CSV,other', {'cells': 'A1'}, 'PACKAGED_CSV'),
                ('a.xlsx', xlsx, {'sheet': 'Data', 'cells': 'A1'}, 'PACKAGED_XLSX')]
    executable = executable.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='gemini-doc-smoke-') as temporary:
        environment = {**os.environ, 'HOME': temporary, 'USERPROFILE': temporary}
        for key in ('API_KEY', 'SUPABASE_URL', 'SUPABASE_ANON_KEY', 'TAVILY_API_KEY'):
            environment.pop(key, None)
        for source, data, selection, token in fixtures:
            request = json.dumps({'source': source, 'bytes': base64.b64encode(data).decode(), 'selection': selection})
            response = subprocess.run([str(executable), '--document-worker'], input=request + '\n',
                cwd=temporary, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=30)
            if response.returncode or not response.stdout:
                raise RuntimeError(f'Packaged worker failed for {source}: exit={response.returncode}, '
                                   f'stderr={response.stderr[:2000]}')
            value = json.loads(response.stdout)
            if response.returncode or value.get('status') != 'ok' or token not in str(value):
                raise RuntimeError(f'Packaged document extraction failed for {source}: {value}')
        if (Path(temporary) / '.gemini_cli').exists():
            raise RuntimeError('Worker unexpectedly created a user profile/log')
    print('Packaged PDF/DOCX/CSV/XLSX worker passed without server keys or profile writes.')


if __name__ == '__main__':
    check(Path(sys.argv[1]))

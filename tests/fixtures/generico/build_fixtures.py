"""Genera cuatro documentos inventados y reproducibles con la biblioteca estándar.

No descarga nada. Nombres, direcciones, municipios y teléfonos son ficticios.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

ROOT = Path(__file__).parent


def archive(path, members):
    with ZipFile(path, 'w') as output:
        for name, content in members.items():
            info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED if name == 'mimetype' else ZIP_DEFLATED
            output.writestr(info, content)


def xlsx(path, rows, date1904=False):
    """Escribe celdas dispersas, shared strings, inline strings y valores nativos."""
    strings = []
    body = []
    for number, row in rows:
        cells = []
        for index, value in enumerate(row, 1):
            if value is None:
                continue
            n, letters = index, ''
            while n:
                n, rem = divmod(n - 1, 26)
                letters = chr(65 + rem) + letters
            ref = letters + str(number)
            if isinstance(value, datetime):
                epoch = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
                serial = (value - epoch).total_seconds() / 86400
                cell = f'<c r="{ref}" s="1"><v>{serial}</v></c>'
            elif isinstance(value, tuple):
                kind, raw = value
                if kind == 'formula':
                    cell = f'<c r="{ref}"><f>{escape(raw)}</f></c>'
                elif kind == 'inline':
                    cell = f'<c r="{ref}" t="inlineStr"><is><t>{escape(raw)}</t></is></c>'
                elif kind == 'iso':
                    cell = f'<c r="{ref}" t="d"><v>{escape(raw)}</v></c>'
                else:
                    cell = f'<c r="{ref}" s="1"><v>{raw}</v></c>'
            else:
                strings.append(str(value))
                cell = f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>'
            cells.append(cell)
        body.append(f'<row r="{number}">' + ''.join(cells) + '</row>')
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    archive(path, {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>',
        '_rels/.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><workbookPr date1904="{int(date1904)}"/><sheets><sheet name="Turnos ficticios" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>',
        'xl/sharedStrings.xml': f'<sst xmlns="{ns}">' + ''.join(f'<si><t>{escape(s)}</t></si>' for s in strings) + '</sst>',
        'xl/styles.xml': f'<styleSheet xmlns="{ns}"><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="22"/></cellXfs></styleSheet>',
        'xl/worksheets/sheet1.xml': f'<worksheet xmlns="{ns}"><sheetData>' + ''.join(body) + '</sheetData></worksheet>',
    })


def ods(path):
    ns = 'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
    def cell(value):
        return '<table:table-cell office:value-type="string"><text:p>' + escape(value) + '</text:p></table:table-cell>'
    def row(values):
        return '<table:table-row>' + ''.join(cell(v) for v in values) + '</table:table-row>'
    header = ['Nombre', 'Direccion', 'Municipio', 'Codigo', '01/11/2026', '02/11/2026', '03/11/2026']
    first = row(['Farmacia Inventada Aurora', 'Calle Imaginaria Uno, 1', 'Villa Ficticia', '001', 'D', '', 'N'])
    second = row(['Farmacia Inventada Prisma', 'Calle Imaginaria Dos, 2', 'Villa Ficticia', '002', 'D', 'X', ''])
    # Filas/celdas vacías repetidas de LibreOffice: no crean datos ni expanden miles de celdas.
    trailing = '<table:table-row table:number-rows-repeated="50000"><table:table-cell table:number-columns-repeated="16384"/></table:table-row>'
    archive(path, {
        'mimetype': 'application/vnd.oasis.opendocument.spreadsheet',
        'META-INF/manifest.xml': '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>',
        'content.xml': f'<office:document-content {ns} office:version="1.2"><office:body><office:spreadsheet><table:table table:name="Calendario ficticio">' + row(header) + first + second + trailing + '</table:table></office:spreadsheet></office:body></office:document-content>',
    })


def pdf(path, pages):
    """PDF mínimo con fuente monoespaciada: la extracción real conserva columnas."""
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'', b'<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>']
    page_refs = []
    for lines in pages:
        page_id = len(objects) + 1
        stream_id = page_id + 1
        page_refs.append(f'{page_id} 0 R')
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1100 800] /Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>'.encode())
        commands = ['BT /F1 8 Tf 30 760 Td 14 TL']
        for line in lines:
            escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            commands.append(f'({escaped}) Tj T*')
        commands.append('ET')
        content = '\n'.join(commands).encode('ascii')
        objects.append(f'<< /Length {len(content)} >>\nstream\n'.encode() + content + b'\nendstream')
    objects[1] = f'<< /Type /Pages /Kids [{" ".join(page_refs)}] /Count {len(pages)} >>'.encode()
    output, offsets = bytearray(b'%PDF-1.4\n'), [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n')
    start = len(output)
    output.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        output.extend(f'{offset:010} 00000 n \n'.encode())
    output.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
    Path(path).write_bytes(output)


def build():
    header = ['Nombre', 'Direccion', 'Municipio', 'CP', 'Telefono', 'Codigo', 'Zona', 'Fecha', 'Inicio', 'Fin', 'Tipo']
    first = [('inline', ' Farmacia   Inventada Aurora '), 'Calle Imaginaria Uno, 1', 'Villa Ficticia', '01001', '900 000 001', '001', 'Zona Inventada Norte', datetime(2026, 11, 1), ('serial', 9 / 24), ('serial', 21 / 24), 'diurna']
    second = ['Farmacia Inventada Prisma', 'Calle Imaginaria Dos, 2', 'Villa Ficticia', '01002', '900000002', '002', 'Zona Inventada Norte', '02/11/2026', '22:00', '08:00', 'nocturna']
    bad_date = list(second)
    bad_date[7] = '31/11/2026'
    bad_phone = list(second)
    bad_phone[5], bad_phone[4], bad_phone[7] = '003', 'no disponible', '03/11/2026'
    xlsx(ROOT / 'filas.xlsx', [(1, ['RESPUESTA TOTALMENTE FICTICIA']), (2, header), (3, first), (4, second), (5, first), (6, bad_date), (7, bad_phone), (8, ['TOTAL'])])
    (ROOT / 'franjas.csv').write_text('Nombre;Direccion;Municipio;CP;Telefono;Zona;Fecha;Franja;NIF\nFarmacia Inventada Bruma;Plaza Imaginaria Tres, 3;Villa Ficticia;01003;900000003;Zona Inventada Sur;01/11/2026;D;FICTICIO-A\nFarmacia Inventada Bruma;Plaza Imaginaria Tres, 3;Villa Ficticia;01003;900000003;Zona Inventada Sur;02/11/2026;N;FICTICIO-A\nFarmacia Inventada Bruma;Plaza Imaginaria Tres, 3;Villa Ficticia;01003;900000003;Zona Inventada Sur;31/11/2026;D;FICTICIO-A\nFarmacia Inventada Bruma;Plaza Imaginaria Tres, 3;Villa Ficticia;01003;900000003;Zona Inventada Sur;03/11/2026;DESCONOCIDA;FICTICIO-A\n', encoding='utf-8')
    ods(ROOT / 'calendario.ods')
    widths = [32, 30, 10, 12, 8, 8, 12]
    def line(values):
        return ''.join(f'{value:<{width}}' for value, width in zip(values, widths)).rstrip()
    lines = [line(['Nombre', 'Direccion', 'Codigo', 'Fecha', 'Inicio', 'Fin', 'Tipo']), line(['Farmacia Inventada Nube', 'Paseo Imaginario Cuatro, 4', '004', '01/11/2026', '09:00', '21:00', 'diurna']), line(['Farmacia Inventada Nube', 'Paseo Imaginario Cuatro, 4', '004', '02/11/2026', '22:00', '08:00', 'nocturna']), line(['Farmacia Inventada Nube', 'Paseo Imaginario Cuatro, 4', '004', 'fecha-mala', '09:00', '21:00', 'diurna'])]
    pdf(ROOT / 'tabla.pdf', [lines, [lines[0], lines[1]]])


if __name__ == '__main__':
    build()

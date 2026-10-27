"""Lectores tabulares locales, sin dependencias de hojas de cálculo.

Las filas y las columnas conservan su posición física (base uno).
Solo se leen valores: no se evalúan fórmulas ni se siguen enlaces externos.
"""
from __future__ import annotations

import csv
import posixpath
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

from ingesta.common import pdf_to_text


@dataclass(frozen=True)
class InvalidCell:
    reason: str


@dataclass
class Table:
    label: str
    rows: list[tuple[int, list]]


def _select(items: list, selector: str | int):
    if isinstance(selector, int):
        if 1 <= selector <= len(items):
            return items[selector - 1]
    else:
        for name, value in items:
            if name == selector:
                return name, value
    raise ValueError(f"Hoja no encontrada: {selector}")


def _xlsx(path: Path, selector: str | int) -> Table:
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    with ZipFile(path) as archive:
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in rels if r.get("TargetMode") != "External"}
        sheets = [(s.get("name"), targets.get(s.get(rel_ns + "id"))) for s in book.findall("s:sheets/s:sheet", ns)]
        name, target = _select(sheets, selector)
        if not target:
            raise ValueError("La hoja no tiene contenido local")
        member = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(n.itertext()) for n in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        date_styles = set()
        if "xl/styles.xml" in archive.namelist():
            styles = ET.fromstring(archive.read("xl/styles.xml"))
            formats = {int(n.get("numFmtId")): n.get("formatCode", "") for n in styles.findall("s:numFmts/s:numFmt", ns)}
            for i, style in enumerate(styles.findall("s:cellXfs/s:xf", ns)):
                fmt = int(style.get("numFmtId", "0"))
                code = re.sub(r'"[^"]*"|\\.|\[[^]]*\]', "", formats.get(fmt, "")).lower()
                if 14 <= fmt <= 22 or 45 <= fmt <= 47 or re.search("[ymdhs]", code):
                    date_styles.add(i)
        props = book.find("s:workbookPr", ns)
        epoch = datetime(1904, 1, 1) if props is not None and props.get("date1904") in {"1", "true"} else datetime(1899, 12, 30)
        rows = []
        for fallback, row in enumerate(ET.fromstring(archive.read(member)).findall("s:sheetData/s:row", ns), 1):
            values = []
            for cell in row.findall("s:c", ns):
                ref = cell.get("r", "")
                match = re.fullmatch(r"([A-Z]+)\d+", ref)
                index = 0
                if match:
                    for char in match[1]:
                        index = index * 26 + ord(char) - 64
                else:
                    index = len(values) + 1
                if index > 16384:
                    raise ValueError("Columna XLSX fuera de rango")
                values.extend([""] * (index - len(values)))
                raw = cell.findtext("s:v", default="", namespaces=ns)
                kind = cell.get("t")
                value = raw
                if kind == "inlineStr":
                    value = "".join(n.text or "" for n in cell.findall("s:is//s:t", ns))
                elif kind == "s":
                    value = strings[int(raw)]
                elif kind == "d":
                    value = datetime.fromisoformat(raw)
                elif kind == "e" or (cell.find("s:f", ns) is not None and not raw):
                    value = InvalidCell("Error de celda o fórmula sin resultado almacenado")
                elif raw and int(cell.get("s", "0")) in date_styles:
                    # Excel reserva un día inexistente en 1900. No se convierte en una fecha real.
                    serial = float(raw)
                    if epoch.year == 1899 and 60 <= serial < 61:
                        value = InvalidCell("Fecha inexistente de Excel (29/02/1900)")
                    else:
                        base = epoch + timedelta(days=1 if epoch.year == 1899 and serial < 60 else 0)
                        value = base + timedelta(days=serial)
                values[index - 1] = value
            rows.append((int(row.get("r", str(fallback))), values))
    return Table(f"hoja {name}", rows)


def _ods(path: Path, selector: str | int) -> Table:
    table_ns = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
    office_ns = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
    text_ns = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("content.xml"))
    name, sheet = _select([(t.get(table_ns + "name"), t) for t in root.iter(table_ns + "table")], selector)
    rows, number = [], 1
    for row in sheet.iter(table_ns + "table-row"):
        values = []
        pending_empty = 0
        for cell in row:
            if cell.tag not in {table_ns + "table-cell", table_ns + "covered-table-cell"}:
                continue
            paragraphs = []
            for paragraph in cell.findall(text_ns + "p"):
                parts = []
                for node in paragraph.iter():
                    if node.tag == text_ns + "s":
                        parts.append(" " * min(int(node.get(text_ns + "c", "1")), 10000))
                    elif node.tag == text_ns + "tab":
                        parts.append("\t")
                    elif node.tag == text_ns + "line-break":
                        parts.append("\n")
                    elif node.text:
                        parts.append(node.text)
                    if node is not paragraph and node.tail:
                        parts.append(node.tail)
                paragraphs.append("".join(parts))
            value = "\n".join(paragraphs)
            kind = cell.get(office_ns + "value-type")
            if kind == "date":
                value = datetime.fromisoformat(cell.get(office_ns + "date-value", ""))
            elif kind == "time":
                raw = cell.get(office_ns + "time-value", "")
                match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", raw)
                if match:
                    hours, minutes, seconds = (float(v or 0) for v in match.groups())
                    value = timedelta(hours=hours, minutes=minutes, seconds=seconds)
                else:
                    value = InvalidCell("Hora ODS no reconocida")
            elif kind in {"float", "currency", "percentage"}:
                value = cell.get(office_ns + "value", value)
            elif cell.get(table_ns + "formula") and not value:
                value = InvalidCell("Fórmula sin resultado almacenado")
            repeat = int(cell.get(table_ns + "number-columns-repeated", "1"))
            if value == "":
                pending_empty += repeat
            else:
                if len(values) + pending_empty + repeat > 16384:
                    raise ValueError("Demasiadas columnas ODS")
                values.extend([""] * pending_empty + [value] * repeat)
                pending_empty = 0
        repeat_rows = int(row.get(table_ns + "number-rows-repeated", "1"))
        if values:
            if len(rows) + repeat_rows > 100000:
                raise ValueError("Demasiadas filas ODS")
            rows.extend((number + i, list(values)) for i in range(repeat_rows))
        number += repeat_rows
    return Table(f"hoja {name}", rows)


def read_tables(path: Path, config: dict) -> list[Table]:
    """Lee una hoja, un CSV o las páginas PDF seleccionadas, sin red."""
    kind = config["type"]
    if kind == "csv":
        with path.open(encoding=config.get("encoding", "utf-8-sig"), newline="") as stream:
            reader = csv.reader(stream, delimiter=config.get("delimiter", ";"), strict=True)
            rows = []
            for row in reader:
                rows.append((reader.line_num, row))
        return [Table("CSV", rows)]
    if kind == "xlsx":
        return [_xlsx(path, config.get("sheet", 1))]
    if kind == "ods":
        return [_ods(path, config.get("sheet", 1))]
    text = pdf_to_text(str(path))
    if not text:
        raise ValueError("PDF sin texto extraíble; no se realiza OCR ni se inventan filas")
    pages = text.split("\f")
    if not pages[-1].strip():
        pages.pop()
    selected = config.get("pages", list(range(1, len(pages) + 1)))
    tables = []
    starts = config["column_starts"]
    for number in selected:
        if number > len(pages):
            raise ValueError(f"Página inexistente: {number}")
        rows = []
        for line_no, line in enumerate(pages[number - 1].splitlines(), 1):
            values = [line[start:end].strip() for start, end in zip(starts, starts[1:] + [None])]
            rows.append((line_no, values))
        tables.append(Table(f"página {number}", rows))
    return tables

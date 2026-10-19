"""Utilidades compartidas por los parsers de ingesta.

Solo dependencias de la stdlib. La extracción de texto usa
`pdftotext -layout` (poppler-utils) vía subprocess; la salida se decodifica
siempre como UTF-8.
"""
from __future__ import annotations

import re
import subprocess
import unicodedata
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")

_XHTML_NS = "{http://www.w3.org/1999/xhtml}"


def pdf_to_text(path: str) -> str | None:
    """Extrae texto con `pdftotext -layout`. None si no hay texto (escaneado).

    La salida se lee como UTF-8 (con reemplazo de bytes inválidos).
    """
    proc = subprocess.run(
        ["pdftotext", "-layout", path, "-"],
        capture_output=True,
        check=False,
    )
    text = proc.stdout.decode("utf-8", errors="replace")
    if not text.strip():
        return None
    return text


def normalize(text: str) -> str:
    """Mayúsculas, sin acentos y con espacios colapsados."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(
        c for c in decomposed if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", without_accents).strip().upper()


def digits_only(text: str) -> str:
    """Devuelve solo los dígitos de un texto."""
    return re.sub(r"\D", "", text)


def pdf_bbox_pages(
    path: str,
) -> list[list[list[tuple[float, float, str]]]] | None:
    """Palabras con coordenadas por página (pdftotext -bbox-layout).

    Devuelve una lista de páginas; cada página es una lista de filas (líneas
    visuales) y cada fila, una lista de (xMin, xMax, texto) ordenada por xMin.
    None si no hay texto o no se puede interpretar. Sin dependencias nuevas:
    el XHTML se lee con xml.etree de la stdlib.
    """
    proc = subprocess.run(
        ["pdftotext", "-bbox-layout", path, "-"],
        capture_output=True,
        check=False,
    )
    data = proc.stdout.decode("utf-8", errors="replace")
    if not data.strip():
        return None
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None

    pages: list[list[list[tuple[float, float, str]]]] = []
    for page in root.iter(_XHTML_NS + "page"):
        words: list[tuple[float, float, float, str]] = []
        for word in page.iter(_XHTML_NS + "word"):
            text = (word.text or "").strip()
            if not text:
                continue
            words.append(
                (
                    float(word.get("yMin", "0")),
                    float(word.get("xMin", "0")),
                    float(word.get("xMax", "0")),
                    text,
                )
            )
        words.sort()
        rows: list[list] = []
        for ymin, xmin, xmax, text in words:
            if rows and abs(ymin - rows[-1][0]) < 3.0:
                rows[-1][1].append((xmin, xmax, text))
            else:
                rows.append([ymin, [(xmin, xmax, text)]])
        for row in rows:
            row[1].sort()
        pages.append([row[1] for row in rows])
    return pages

"""Genera la transcripción de texto del PDF escaneado de Sant Antoni (Baleares 2026).

El PDF oficial `data/raw/baleares/2026/Sant_Antoni.pdf` no tiene capa de texto:
son 730 imágenes de 595x842 px (cada día aparece dos veces). Como el documento es
una impresión de una página web, cada línea repetida (cabeceras de turno y filas
de farmacia) es idéntica píxel a píxel en todas las páginas. Por eso:

1. Se extraen las imágenes con `pdfimages` (poppler) en formato PPM.
2. Cada página se corta en bandas de texto y cada banda se identifica por el
   MD5 de sus píxeles.
3. Las bandas conocidas (cabeceras y las 10 farmacias) se sustituyen por su texto,
   transcrito una sola vez por lectura visual de la imagen (ver TRANSCRIPCION).
   Si aparece una banda desconocida que no sea fecha ni pie de página, el script
   se detiene: nada se rellena por aproximación.
4. La fecha de cada página se deduce de su posición (1 de enero + n) y se
   comprueba contra el OCR (tesseract) de la línea de fecha y contra el número
   del pie "Página N de 365". Cualquier discrepancia detiene el script.

Salida: `data/raw/baleares/2026/Sant_Antoni.txt`, con el mismo formato que
`pdftotext -layout` (una página por día, separadas por \\f). El parser de
Baleares la usa automáticamente cuando el PDF no tiene texto.

Requisitos (solo para regenerar la transcripción): poppler-utils (`pdfimages`) y
tesseract. El parser NO los necesita.

Uso:
    python scripts/transcribir_sant_antoni.py
"""
from __future__ import annotations

import difflib
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_PATH = os.path.join(BASE_DIR, "data", "raw", "baleares", "2026", "Sant_Antoni.pdf")
OUT_PATH = os.path.join(BASE_DIR, "data", "raw", "baleares", "2026", "Sant_Antoni.txt")
YEAR = 2026

# MD5 (10 primeros caracteres) de la banda -> (tipo, texto). Transcripción visual
# de cada imagen, revisada a 4x de ampliación (19/10/2026).
TRANSCRIPCION: dict[str, tuple[str, str]] = {
    "fd9313937c": ("cabecera", "Servei Farmacèutic d'urgència:"),
    "cc97058eeb": ("zona", "SANT ANTONI"),
    "65c1396611": ("regla", ""),
    "f6afd57c36": ("turno", "SERVEI D'URGÈNCIA DIURN de 09:00 a 21:00"),
    "482d9a7259": ("turno", "SERVEI D'URGÈNCIA NOCTURN de 21:00 a 09:00"),
    "f93aff441d": ("farmacia", "PUGET FUSTE|BALANZAT,3|971340449"),
    "40fc2ba630": ("farmacia", "PETIT ALFOS|AV.CALA DE BOU, 43 - CALA DE BOU - SANT JOSEP|971345266"),
    "025e804625": ("farmacia", "TORRES RIBAS|CIRERERS, S/N.|971345155"),
    "2a6d3ffb55": ("farmacia", "VILLANGÒMEZ MARÍ|CARRER AMPLE, 12|971340891"),
    "36fda626d1": ("farmacia", "RAMON COSTA|CL ISIDOR MACABICH, 2|971346421"),
    "a751a6c328": ("farmacia", "MANZANO AUSIN|CARRER BARCELONA, S/N|971348990"),
    "086817d2a7": ("farmacia", "TORRES PONS|CARRER ES CALÓ, 50 - CALA DE BOU - SANT JOSEP|971803146"),
    "da466a86fb": ("farmacia", "BRU BONILLA|AV. D' ISIDOR MACABICH, 13B|971724707"),
    "fe87897854": ("farmacia", "CABRERA JAUME|C/ BARTOMEU VICENT RAMON, 13|646359555"),
    "aeed03e21f": ("farmacia", "SANTOS GOMEZ|CARRER RAMON I CAJAL, 40|971483426"),
}

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
    "septiembre", "octubre", "noviembre", "diciembre",
]


def read_ppm_gray(path: str) -> tuple[int, int, bytes]:
    """Lee un PPM (P6) o PGM (P5) y lo devuelve en gris (ITU-R 601-2, redondeo de Pillow)."""
    with open(path, "rb") as fh:
        data = fh.read()
    tokens: list[bytes] = []
    pos = 0
    while len(tokens) < 4:
        while data[pos : pos + 1].isspace():
            pos += 1
        if data[pos : pos + 1] == b"#":
            pos = data.index(b"\n", pos) + 1
            continue
        end = pos
        while not data[end : end + 1].isspace():
            end += 1
        tokens.append(data[pos:end])
        pos = end
    pos += 1
    magic, width, height = tokens[0], int(tokens[1]), int(tokens[2])
    raw = data[pos:]
    if magic == b"P5":
        return width, height, raw[: width * height]
    if magic != b"P6":
        raise ValueError(f"formato no soportado: {magic!r}")
    gray = bytearray(width * height)
    for i in range(width * height):
        r, g, b = raw[3 * i], raw[3 * i + 1], raw[3 * i + 2]
        gray[i] = (r * 19595 + g * 38470 + b * 7471 + 0x8000) >> 16
    return width, height, bytes(gray)


def text_bands(width: int, height: int, gray: bytes) -> list[tuple[int, int]]:
    """Bandas horizontales con píxeles oscuros (< 200), uniendo huecos de <= 2 px."""
    bands: list[list[int]] = []
    inside = False
    start = 0
    for y in range(height):
        row = gray[y * width : (y + 1) * width]
        dark = any(v < 200 for v in row)
        if dark and not inside:
            start, inside = y, True
        elif not dark and inside:
            bands.append([start, y])
            inside = False
    if inside:
        bands.append([start, height])
    merged: list[list[int]] = []
    for band in bands:
        if merged and band[0] - merged[-1][1] <= 2:
            merged[-1][1] = band[1]
        else:
            merged.append(band)
    return [(a, b) for a, b in merged]


def band_hash(width: int, gray: bytes, top: int, bottom: int) -> str:
    return hashlib.md5(gray[top * width : bottom * width]).hexdigest()[:10]


def ocr_band(width: int, gray: bytes, top: int, bottom: int, workdir: str) -> str:
    """OCR de una banda ampliada 4x (vecino más próximo) con tesseract."""
    if shutil.which("tesseract") is None:
        return ""
    scale = 4
    h = bottom - top
    rows = []
    for y in range(h):
        line = gray[(top + y) * width : (top + y + 1) * width]
        wide = bytes(v for v in line for _ in range(scale))
        rows.extend([wide] * scale)
    path = os.path.join(workdir, "band.pgm")
    with open(path, "wb") as fh:
        fh.write(f"P5 {width * scale} {h * scale} 255\n".encode())
        fh.write(b"".join(rows))
    out = subprocess.run(
        ["tesseract", path, "-", "--psm", "7"], capture_output=True, text=True, check=False
    )
    return out.stdout.strip()


def date_line(day: date) -> str:
    return f"{_DIAS[day.weekday()]}, {day.day} de {_MESES[day.month - 1]} de {day.year}"


def pharmacy_line(text: str) -> str:
    holder, address, phone = text.split("|")
    return f"{holder:<34}{address:<56}{phone}"


def main() -> int:
    workdir = tempfile.mkdtemp(prefix="sant_antoni_")
    try:
        subprocess.run(["pdfimages", PDF_PATH, os.path.join(workdir, "p")], check=True)
        images = sorted(glob.glob(os.path.join(workdir, "p-*.p?m")))
        if len(images) != 730:
            print(f"Se esperaban 730 imágenes y hay {len(images)}", file=sys.stderr)
            return 1
        pages: list[str] = []
        ocr_checked = 0
        unverified: list[int] = []
        doubtful_digits: list[int] = []
        for index in range(0, len(images), 2):
            with open(images[index], "rb") as f1, open(images[index + 1], "rb") as f2:
                same = f1.read() == f2.read()
            if not same:
                print(f"Las imágenes {index} y {index + 1} no son copia", file=sys.stderr)
                return 1
            w1, h1, g1 = read_ppm_gray(images[index])
            day = date(YEAR, 1, 1) + timedelta(days=index // 2)
            page_no = index // 2 + 1
            lines: list[str] = []
            for top, bottom in text_bands(w1, h1, g1):
                key = band_hash(w1, g1, top, bottom)
                if key in TRANSCRIPCION:
                    kind, text = TRANSCRIPCION[key]
                    if kind == "cabecera":
                        lines.append(text)
                    elif kind == "zona":
                        lines += [text, ""]
                    elif kind == "turno":
                        lines.append(" " * 18 + text)
                    elif kind == "farmacia":
                        lines.append(pharmacy_line(text))
                    continue
                ocr = ocr_band(w1, g1, top, bottom, workdir)
                if top > h1 * 0.9:
                    match = re.search(r"P.gina\s+(\d+)\s+de\s+(\d+)", ocr)
                    if match and (int(match.group(1)), int(match.group(2))) != (page_no, 365):
                        print(f"Pie de página {ocr!r} != {page_no}", file=sys.stderr)
                        return 1
                    lines += ["", "", f"01/01/{YEAR} - 31/12/{YEAR}" + " " * 48 + f"Página {page_no} de 365"]
                    continue
                match = re.search(r"(\d{1,2})\s+de\s+([a-zé]+)", ocr.lower())
                if not re.search(r"\bde\b", ocr.lower()):
                    print(f"Banda desconocida en la página {page_no}: {ocr!r}", file=sys.stderr)
                    return 1
                if match is None:
                    unverified.append(page_no)
                    lines += ["", date_line(day)]
                    continue
                month_ok = difflib.SequenceMatcher(
                    None, match.group(2), _MESES[day.month - 1]
                ).ratio() >= 0.75
                first_word = re.match(r"\s*([a-záéíóú]+)", ocr.lower())
                weekday = None
                if first_word:
                    scores = [
                        difflib.SequenceMatcher(None, first_word.group(1), d).ratio()
                        for d in _DIAS
                    ]
                    if max(scores) >= 0.75:
                        weekday = scores.index(max(scores))
                if weekday is not None and weekday != day.weekday():
                    print(f"Día de la semana OCR {ocr!r} != {day.isoformat()}", file=sys.stderr)
                    return 1
                if not month_ok:
                    print(f"Mes OCR {ocr!r} != {day.isoformat()}", file=sys.stderr)
                    return 1
                if int(match.group(1)) != day.day:
                    if weekday is None:
                        print(f"Fecha OCR {ocr!r} != {day.isoformat()}", file=sys.stderr)
                        return 1
                    doubtful_digits.append(page_no)
                ocr_checked += 1
                lines += ["", date_line(day)]
            pages.append("\n".join(lines) + "\n")
        with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\f".join(pages))
        print(f"{len(pages)} días transcritos; fechas verificadas por OCR: {ocr_checked}")
        if doubtful_digits:
            print(
                "Páginas con el número de día mal leído por el OCR pero día de la semana "
                f"y mes correctos: {doubtful_digits}"
            )
        if unverified:
            print(f"Páginas con fecha ilegible para el OCR (fecha por posición): {unverified}")
        print(f"Salida: {OUT_PATH}")
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

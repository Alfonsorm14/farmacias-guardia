"""Parser de la ciudad de Madrid (Portal de datos abiertos del Ayuntamiento de Madrid).

Fuente: conjunto "Farmacias de guardia" (datos.madrid.es, id 214440, licencia
CC BY 4.0). Cada mes se publica un PDF de texto "TURNOS DE URGENCIA PERIODO <MES>
<AÑO>" con una fila por farmacia y día: localidad, distrito, fecha, número de
farmacia, dirección, horario y teléfono. La fuente no da el nombre del titular,
solo el número de oficina de farmacia.

Los PDF se guardan en data/raw/madrid/ como madrid_AAAA-MM.pdf (uno por mes).

El mismo conjunto publica un CSV anual ("Farmacias de guardia AAAA", UTF-8 con BOM, separador ";")
con las mismas filas (Municipio;Barrio;Fecha;Farmacia;Dirección;Duración;Teléfono). Se guarda como
data/raw/madrid/madrid_AAAA.csv y se usan sus filas desde hace 31 días. Si un mismo día está en el
PDF y en el CSV y no coinciden, se avisa (PDF_CSV_DIFIEREN) y ese día manda el PDF; los duplicados
exactos se cuentan una vez.

Uso:
    from ingesta.parsers.madrid import parse_dir
    result = parse_dir("data/raw/madrid")
"""
from __future__ import annotations

import csv
import glob
import os
import re
from datetime import date, datetime, time, timedelta

from ingesta.common import TZ, pdf_to_text
from ingesta.model import DutyShift, ParseResult, Pharmacy, SourceInfo

REGION = "13"  # Comunidad de Madrid (solo municipio de Madrid)
SOURCE_ID = "MAD-AYTO-DATOSABIERTOS"
PUBLISHER = "Ayuntamiento de Madrid — Portal de datos abiertos"
URL = "https://datos.madrid.es/dataset/214440-0-farmacias-guardia"
LICENSE = "CC BY 4.0"
DOWNLOAD_URL = (
    "https://datos.madrid.es/dataset/214440-0-farmacias-guardia/resource/"
    "214440-18-farmacias-guardia/download/madrid-con-f.pdf"
)

_ROW_RE = re.compile(
    r"^(?P<localidad>\S.*?)\s{2,}(?P<distrito>\S.*?)\s{2,}(?P<fecha>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<numero>\d+)\s+(?P<direccion>\S.*?)\s{2,}(?P<horario>SERVICIO.*?\))\s+(?P<telefono>\d[\d ]{8,})\s*$"
)
_HOURS_RE = re.compile(r"\((\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*H(\s+D[IÍ]A SIGUIENTE)?\)", re.I)
_FILE_RE = re.compile(r"madrid_(\d{4})-(\d{2})\.pdf$")
_CSV_RE = re.compile(r"madrid_(\d{4})\.csv$")
CSV_COLUMNS = ["Municipio", "Barrio", "Fecha", "Farmacia", "Dirección", "Duración", "Teléfono"]


def parse_line(line: str) -> dict[str, str] | None:
    match = _ROW_RE.match(line.rstrip())
    return match.groupdict() if match else None


def _shift_times(day: date, horario: str) -> tuple[datetime, datetime, str, bool] | None:
    match = _HOURS_RE.search(horario)
    if not match:
        return None
    h1, m1, h2, m2 = (int(match.group(i)) for i in range(1, 5))
    if h1 > 23 or h2 > 24 or m1 > 59 or m2 > 59 or (h2 == 24 and m2 != 0):
        return None
    start = datetime.combine(day, time(h1, m1), TZ)
    next_day = h2 == 24 or bool(match.group(5)) or (h2, m2) <= (h1, m1)
    end = datetime.combine(day + timedelta(days=1 if next_day else 0), time(h2 % 24, m2), TZ)
    upper = horario.upper()
    if "24 HORAS" in upper or (next_day and (h1, m1) == (h2, m2)):
        kind = "24h"
    elif "NOCTURN" in upper:
        kind = "nocturna"
    else:
        kind = "diurna"
    return start, end, kind, True


def _row_to_records(
    row: dict[str, str], where: str, warnings: list[str]
) -> tuple[Pharmacy, DutyShift] | None:
    """Fila normalizada (localidad, distrito, fecha, numero, direccion, horario, telefono)."""
    try:
        day = datetime.strptime(row["fecha"], "%d/%m/%Y").date()
    except ValueError:
        warnings.append(f"{where}: FECHA_NO_RECONOCIDA: {row['fecha']}")
        return None
    times = _shift_times(day, row["horario"])
    if times is None:
        warnings.append(f"{where}: HORARIO_NO_RECONOCIDO: {row['horario']}")
        return None
    start, end, kind, exact = times
    pharmacy_id = f"MAD:{int(row['numero'])}"
    phone = re.sub(r"\D", "", row["telefono"])
    pharmacy = Pharmacy(
        id=pharmacy_id,
        region=REGION,
        holder=f"nº {int(row['numero'])}",
        address=re.sub(r"\s+", " ", row["direccion"]).strip(),
        locality=row["localidad"].strip().title() or None,
        postal_code=None,
        phone=phone if len(phone) == 9 else None,
        duty_phone=None,
    )
    shift = DutyShift(
        pharmacy_id=pharmacy_id,
        zone=f"MADRID - {row['distrito'].strip()}",
        start=start,
        end=end,
        kind=kind,
        raw_label=re.sub(r"\s+", " ", row["horario"]).strip(),
        times_exact=exact,
    )
    return pharmacy, shift


def _parse_csv(
    path: str, warnings: list[str], today: date | None = None
) -> tuple[dict[str, Pharmacy], list[DutyShift]]:
    """CSV anual del portal; solo las filas desde hace 31 días (las anteriores ya no sirven)."""
    filename = os.path.basename(path)
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        if reader.fieldnames != CSV_COLUMNS:
            warnings.append(f"{filename}: COLUMNAS_INESPERADAS: {reader.fieldnames}")
            return {}, []
        rows = list(reader)
    desde = (today or date.today()) - timedelta(days=31)
    pharmacies: dict[str, Pharmacy] = {}
    shifts: list[DutyShift] = []
    for n, r in enumerate(rows, start=2):
        if any(not (r.get(k) or "").strip() for k in CSV_COLUMNS[:-1]) or None in r:
            warnings.append(f"{filename} l{n}: FILA_INCOMPLETA: {r}")
            continue
        try:
            if datetime.strptime(r["Fecha"] or "", "%d/%m/%Y").date() < desde:
                continue
        except ValueError:
            warnings.append(f"{filename} l{n}: FECHA_NO_RECONOCIDA: {r['Fecha']}")
            continue
        if not (r["Farmacia"] or "").strip().isdigit():
            warnings.append(f"{filename} l{n}: LINEA_NO_RECONOCIDA: {r}")
            continue
        rec = _row_to_records(
            {
                "localidad": r["Municipio"], "distrito": r["Barrio"], "fecha": r["Fecha"],
                "numero": r["Farmacia"], "direccion": r["Dirección"], "horario": r["Duración"],
                "telefono": r["Teléfono"] or "",
            },
            f"{filename} l{n}",
            warnings,
        )
        if rec:
            pharmacies[rec[0].id] = rec[0]
            shifts.append(rec[1])
    return pharmacies, shifts


def _parse_file(path: str, warnings: list[str]) -> tuple[dict[str, Pharmacy], list[DutyShift]]:
    filename = os.path.basename(path)
    text = pdf_to_text(path)
    if text is None:
        warnings.append(f"{filename}: SIN_TEXTO")
        return {}, []
    pharmacies: dict[str, Pharmacy] = {}
    shifts: list[DutyShift] = []
    for page, raw_page in enumerate(text.split("\f"), start=1):
        for line in raw_page.split("\n"):
            stripped = line.strip()
            if not re.search(r"\d{2}/\d{2}/\d{4}", stripped) or stripped.startswith("TURNOS"):
                continue
            row = parse_line(line)
            if row is None:
                warnings.append(f"{filename} p{page}: LINEA_NO_RECONOCIDA: {stripped}")
                continue
            rec = _row_to_records(row, f"{filename} p{page}", warnings)
            if rec:
                pharmacies[rec[0].id] = rec[0]
                shifts.append(rec[1])
    return pharmacies, shifts


def parse_dir(path: str, retrieved_at: datetime | None = None, today: date | None = None) -> ParseResult:
    """Procesa los PDF mensuales madrid_AAAA-MM.pdf y los CSV anuales madrid_AAAA.csv del directorio."""
    pharmacies: dict[str, Pharmacy] = {}
    shifts: list[DutyShift] = []
    warnings: list[str] = []
    by_origin: dict[str, list[DutyShift]] = {"pdf": [], "csv": []}
    for file in sorted(glob.glob(os.path.join(path, "madrid_*.pdf"))):
        if not _FILE_RE.search(file):
            continue
        p, s = _parse_file(file, warnings)
        pharmacies.update(p)
        by_origin["pdf"].extend(s)
    for file in sorted(glob.glob(os.path.join(path, "madrid_*.csv"))):
        if not _CSV_RE.search(file):
            continue
        p, s = _parse_csv(file, warnings, today)
        for pid, ph in p.items():
            pharmacies.setdefault(pid, ph)
        by_origin["csv"].extend(s)
    # Contraste: los días que están en los dos deben coincidir.
    def by_day(items: list[DutyShift]) -> dict[date, set]:
        out: dict[date, set] = {}
        for s in items:
            out.setdefault(s.start.date(), set()).add((s.pharmacy_id, s.start, s.end, s.kind))
        return out
    pdf_days, csv_days = by_day(by_origin["pdf"]), by_day(by_origin["csv"])
    discrepantes = set()
    for day in sorted(set(pdf_days) & set(csv_days)):
        if pdf_days[day] != csv_days[day]:
            diff = sorted(pid for pid, *_ in pdf_days[day] ^ csv_days[day])
            warnings.append(f"PDF_CSV_DIFIEREN {day:%d/%m/%Y}: {', '.join(diff)} (se usa el PDF)")
            discrepantes.add(day)
    shifts = by_origin["pdf"] + [s for s in by_origin["csv"] if s.start.date() not in discrepantes]
    # Un mismo turno repetido (dos descargas del mismo mes, PDF y CSV, filas duplicadas del CSV)
    # se cuenta una vez.
    unique = {(s.pharmacy_id, s.start, s.kind): s for s in shifts}
    files = [f for f in glob.glob(os.path.join(path, "madrid_*.*")) if _FILE_RE.search(f) or _CSV_RE.search(f)]
    if retrieved_at is None and files:
        # Fecha de descarga = última modificación del PDF más reciente (determinista).
        retrieved_at = datetime.fromtimestamp(max(os.path.getmtime(f) for f in files), TZ)
    source = SourceInfo(
        source_id=SOURCE_ID,
        publisher=PUBLISHER,
        url=URL,
        license=LICENSE,
        retrieved_at=retrieved_at or datetime.now(TZ),
    )
    return ParseResult(source, pharmacies, sorted(unique.values(), key=lambda s: (s.start, s.pharmacy_id)), warnings)

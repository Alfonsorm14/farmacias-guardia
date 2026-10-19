"""Parser de la ciudad de Madrid (Portal de datos abiertos del Ayuntamiento de Madrid).

Fuente: conjunto "Farmacias de guardia" (datos.madrid.es, id 214440, licencia
CC BY 4.0). Cada mes se publica un PDF de texto "TURNOS DE URGENCIA PERIODO <MES>
<AÑO>" con una fila por farmacia y día: localidad, distrito, fecha, número de
farmacia, dirección, horario y teléfono. La fuente no da el nombre del titular,
solo el número de oficina de farmacia.

Los PDF se guardan en data/raw/madrid/ como madrid_AAAA-MM.pdf (uno por mes).

Uso:
    from ingesta.parsers.madrid import parse_dir
    result = parse_dir("data/raw/madrid")
"""
from __future__ import annotations

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


def parse_line(line: str) -> dict[str, str] | None:
    match = _ROW_RE.match(line.rstrip())
    return match.groupdict() if match else None


def _shift_times(day: date, horario: str) -> tuple[datetime, datetime, str, bool] | None:
    match = _HOURS_RE.search(horario)
    if not match:
        return None
    h1, m1, h2, m2 = (int(match.group(i)) for i in range(1, 5))
    start = datetime.combine(day, time(h1 % 24, m1), TZ)
    next_day = bool(match.group(5)) or (h2, m2) <= (h1, m1)
    end = datetime.combine(day + timedelta(days=1 if next_day else 0), time(h2 % 24, m2), TZ)
    upper = horario.upper()
    if "24 HORAS" in upper or (next_day and (h1, m1) == (h2, m2)):
        kind = "24h"
    elif "NOCTURN" in upper:
        kind = "nocturna"
    else:
        kind = "diurna"
    return start, end, kind, True


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
            day = datetime.strptime(row["fecha"], "%d/%m/%Y").date()
            times = _shift_times(day, row["horario"])
            if times is None:
                warnings.append(f"{filename} p{page}: HORARIO_NO_RECONOCIDO: {row['horario']}")
                continue
            start, end, kind, exact = times
            pharmacy_id = f"MAD:{int(row['numero'])}"
            phone = re.sub(r"\D", "", row["telefono"])
            pharmacies[pharmacy_id] = Pharmacy(
                id=pharmacy_id,
                region=REGION,
                holder=f"nº {int(row['numero'])}",
                address=re.sub(r"\s+", " ", row["direccion"]).strip(),
                locality=row["localidad"].strip().title() or None,
                postal_code=None,
                phone=phone if len(phone) == 9 else None,
                duty_phone=None,
            )
            shifts.append(
                DutyShift(
                    pharmacy_id=pharmacy_id,
                    zone=f"MADRID - {row['distrito'].strip()}",
                    start=start,
                    end=end,
                    kind=kind,
                    raw_label=row["horario"].strip(),
                    times_exact=exact,
                )
            )
    return pharmacies, shifts


def parse_dir(path: str, retrieved_at: datetime | None = None) -> ParseResult:
    """Procesa todos los PDF mensuales madrid_AAAA-MM.pdf del directorio."""
    pharmacies: dict[str, Pharmacy] = {}
    shifts: list[DutyShift] = []
    warnings: list[str] = []
    for file in sorted(glob.glob(os.path.join(path, "madrid_*.pdf"))):
        if not _FILE_RE.search(file):
            continue
        p, s = _parse_file(file, warnings)
        pharmacies.update(p)
        shifts.extend(s)
    # Un mismo turno repetido (p. ej. dos descargas del mismo mes) se cuenta una vez.
    unique = {(s.pharmacy_id, s.start, s.kind): s for s in shifts}
    files = [f for f in glob.glob(os.path.join(path, "madrid_*.pdf")) if _FILE_RE.search(f)]
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

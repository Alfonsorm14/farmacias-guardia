"""Parser de la ciudad de Zaragoza (servicio de datos del Ayuntamiento de Zaragoza).

Fuente: https://www.zaragoza.es/sede/servicio/farmacia.json — devuelve las
farmacias de guardia del DÍA EN CURSO con titular, dirección, teléfono, turno,
horario literal, sector y coordenadas WGS84. No admite consultar otras fechas,
así que se guarda una descarga diaria en data/raw/zaragoza/ y el parser las une.

Condiciones de reutilización (aviso legal de zaragoza.es): reutilización para
fines comerciales y no comerciales, citando la fuente, sin desnaturalizar la
información y conservando la fecha de actualización.

Uso:
    from ingesta.parsers.zaragoza import parse_dir
    result = parse_dir("data/raw/zaragoza")
"""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import datetime, time, timedelta

from ingesta.common import TZ, digits_only
from ingesta.model import DutyShift, ParseResult, Pharmacy, SourceInfo

REGION = "02"  # Aragón (solo municipio de Zaragoza)
SOURCE_ID = "ZGZ-AYTO"
PUBLISHER = "Ayuntamiento de Zaragoza — Servicio de datos de farmacias de guardia"
URL = "https://www.zaragoza.es/sede/servicio/farmacia/"
LICENSE = "Condiciones generales de reutilización del Ayuntamiento de Zaragoza (citar la fuente)"
DOWNLOAD_URL = "https://www.zaragoza.es/sede/servicio/farmacia.json?rows=500&srsname=wgs84"

_FILE_RE = re.compile(r"farmacias_guardia_(\d{8})\.json$")
_HOURS_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*h\.?\s*a\s*(?:las\s*)?(\d{1,2})(?::(\d{2}))?\s*h", re.I)


def _times(day, horario: str) -> tuple[datetime, datetime, str, bool]:
    match = _HOURS_RE.search(horario or "")
    if not match:
        # Sin horario reconocible: día completo, marcado como no confirmado.
        start = datetime.combine(day, time(0), TZ)
        return start, start + timedelta(days=1), "24h", False
    h1, m1 = int(match.group(1)), int(match.group(2) or 0)
    h2, m2 = int(match.group(3)), int(match.group(4) or 0)
    start = datetime.combine(day, time(h1 % 24, m1), TZ)
    next_day = "siguiente" in (horario or "").lower() or (h2, m2) <= (h1, m1)
    end = datetime.combine(day + timedelta(days=1 if next_day else 0), time(h2 % 24, m2), TZ)
    if next_day and (h1, m1) == (h2, m2):
        kind = "24h"
    elif next_day:
        kind = "nocturna"
    else:
        kind = "diurna"
    return start, end, kind, True


def _records(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return [r for r in data.get("result", []) if isinstance(r, dict) and r.get("guardia")]


def parse_dir(path: str, retrieved_at: datetime | None = None) -> ParseResult:
    pharmacies: dict[str, Pharmacy] = {}
    by_day: dict[str, list[DutyShift]] = {}
    warnings: list[str] = []
    latest = None
    for file in sorted(glob.glob(os.path.join(path, "farmacias_guardia_*.json"))):
        if not _FILE_RE.search(file):
            continue
        latest = _FILE_RE.search(file).group(1)
        try:
            records = _records(file)
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"{os.path.basename(file)}: FICHERO_ILEGIBLE: {exc}")
            continue
        file_days: dict[str, list[DutyShift]] = {}
        for rec in records:
            g = rec["guardia"]
            try:
                day = datetime.fromisoformat(g["fecha"]).date()
            except (KeyError, ValueError):
                warnings.append(f"{os.path.basename(file)}: FECHA_INVALIDA {rec.get('id')}")
                continue
            pid = f"ZGZ:{rec['id']}"
            holder = re.sub(r"^Farmacia\s+", "", rec.get("title", "")).strip()
            digits = digits_only(rec.get("telefonos", ""))
            if digits.startswith("34") and len(digits) >= 11:
                digits = digits[2:]
            phone = digits[:9] if digits[:1] in "6789" else ""
            pharmacies[pid] = Pharmacy(
                id=pid,
                region=REGION,
                holder=holder,
                address=(rec.get("calle") or "").strip(),
                locality="Zaragoza",
                postal_code=None,
                phone=phone if len(phone) == 9 else None,
                duty_phone=None,
            )
            start, end, kind, exact = _times(day, g.get("horario", ""))
            if not exact:
                warnings.append(f"{os.path.basename(file)}: HORARIO_NO_RECONOCIDO {pid}: {g.get('horario')}")
            file_days.setdefault(day.isoformat(), []).append(DutyShift(
                pharmacy_id=pid,
                zone=f"ZARAGOZA - {g.get('sector') or g.get('turno') or ''}".strip(" -"),
                start=start,
                end=end,
                kind=kind,
                raw_label=f"{g.get('turno', '')} {g.get('horario', '')}".strip(),
                times_exact=exact,
            ))
        # Para cada fecha manda la descarga más reciente.
        by_day.update(file_days)
    shifts = {(sh.pharmacy_id, sh.start): sh for lst in by_day.values() for sh in lst}
    used = {sh.pharmacy_id for sh in shifts.values()}
    pharmacies = {pid: ph for pid, ph in pharmacies.items() if pid in used}
    if retrieved_at is None and latest:
        retrieved_at = datetime.strptime(latest, "%Y%m%d").replace(tzinfo=TZ)
    source = SourceInfo(SOURCE_ID, PUBLISHER, URL, LICENSE, retrieved_at or datetime.now(TZ))
    return ParseResult(source, pharmacies, sorted(shifts.values(), key=lambda s: (s.start, s.pharmacy_id)), warnings)


def load_coordinates(path: str) -> dict[str, tuple[float, float]]:
    """ZGZ:<id> -> (lat, lon) según la geometría publicada por el Ayuntamiento."""
    out: dict[str, tuple[float, float]] = {}
    for file in sorted(glob.glob(os.path.join(path, "farmacias_guardia_*.json"))):
        for rec in _records(file):
            coords = (rec.get("geometry") or {}).get("coordinates")
            if isinstance(coords, list) and len(coords) == 2:
                out[f"ZGZ:{rec['id']}"] = (float(coords[1]), float(coords[0]))
    return out

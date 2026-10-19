"""Parser de la Comunidad Foral de Navarra (datos abiertos del Gobierno de Navarra).

Fuente: conjunto "Farmacias de guardia" de datosabiertos.navarra.es (CC BY 4.0),
una fila por farmacia y día con: fecha, desde, hasta (horas enteras), localidad,
grupo (zona de guardia), dirección, farmacia (titular), cod_Farmacia y teléfono.
El conjunto es una ventana móvil de unas dos semanas que se actualiza a diario,
así que se guarda cada descarga en data/raw/navarra/ y el parser une todas
(la descarga más reciente manda si un mismo día y farmacia aparecen varias veces).

Coordenadas: el Gobierno de Navarra publica además la capa oficial de farmacias
(IDENA, "DOTACI_Sym_Farmacias", CC BY 4.0) con coordenadas ETRS89/UTM 30N por
código de farmacia; `load_idena` la lee (DBF, solo librería estándar) y la
convierte a WGS84 para que el geocodificador no tenga que buscar direcciones.

Uso:
    from ingesta.parsers.navarra import parse_dir
    result = parse_dir("data/raw/navarra")
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import struct
from datetime import date, datetime, time, timedelta

from ingesta.common import TZ, digits_only
from ingesta.model import DutyShift, ParseResult, Pharmacy, SourceInfo

REGION = "15"
SOURCE_ID = "NA-DATOSABIERTOS"
PUBLISHER = "Gobierno de Navarra — Departamento de Salud (Open Data Navarra)"
URL = "https://datosabiertos.navarra.es/dataset/farmacias-de-guardia"
LICENSE = "CC BY 4.0"
DOWNLOAD_URL = (
    "https://datosabiertos.navarra.es/datastore/dump/"
    "e309e89e-d62e-4222-b6fa-e81d0924a086?format=json"
)
IDENA_URL = "https://idena.navarra.es/descargas/DOTACI_Sym_Farmacias.zip"

_FILE_RE = re.compile(r"farmacias_guardia_(\d{8})\.json$")


def _kind(start_hour: int, end_hour: int) -> str:
    if start_hour == end_hour:
        return "24h"
    if end_hour < start_hour:
        return "nocturna"
    return "diurna"


def _hour(text: str) -> int | None:
    match = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*", text or "")
    if not match:
        return None
    value = int(match.group(1))
    return value if 0 <= value <= 24 else None


def _parse_records(
    records: list[list], filename: str, warnings: list[str]
) -> tuple[dict[str, Pharmacy], dict[tuple[str, date, str], DutyShift]]:
    pharmacies: dict[str, Pharmacy] = {}
    shifts: dict[tuple[str, date, str], DutyShift] = {}
    for row in records:
        if len(row) < 10:
            warnings.append(f"{filename}: FILA_INCOMPLETA: {row}")
            continue
        _rid, fecha, desde, hasta, localidad, grupo, direccion, titular, codigo, telefono = row[:10]
        try:
            day = datetime.strptime(fecha.strip(), "%d/%m/%Y").date()
        except (ValueError, AttributeError):
            warnings.append(f"{filename}: FECHA_INVALIDA {codigo}: {fecha}")
            continue
        start_h, end_h = _hour(desde), _hour(hasta)
        if start_h is None or end_h is None or not codigo:
            warnings.append(f"{filename}: HORARIO_INVALIDO {codigo}: {desde}-{hasta}")
            continue
        pharmacy_id = f"NA:{codigo.strip()}"
        phone = digits_only(telefono or "")
        pharmacies[pharmacy_id] = Pharmacy(
            id=pharmacy_id,
            region=REGION,
            holder=re.sub(r"\s+", " ", titular or "").strip(),
            address=re.sub(r"\s+", " ", direccion or "").strip(),
            locality=(localidad or "").strip() or None,
            postal_code=None,
            phone=phone if len(phone) == 9 else None,
            duty_phone=None,
        )
        kind = _kind(start_h, end_h)
        start = datetime.combine(day, time(start_h % 24), TZ)
        end_day = day + timedelta(days=1) if end_h <= start_h else day
        end = datetime.combine(end_day, time(0), TZ) + timedelta(hours=end_h)
        label = f"{grupo} ({start_h}-{end_h} h)"
        shifts[(pharmacy_id, day, kind)] = DutyShift(
            pharmacy_id=pharmacy_id,
            zone=(grupo or "").strip(),
            start=start,
            end=end,
            kind=kind,
            raw_label=label,
        )
    return pharmacies, shifts


def parse_dir(path: str, retrieved_at: datetime | None = None) -> ParseResult:
    """Une todas las descargas diarias guardadas en `path`."""
    files = sorted(
        (f for f in glob.glob(os.path.join(path, "farmacias_guardia_*.json")) if _FILE_RE.search(f)),
        key=lambda f: _FILE_RE.search(f).group(1),
    )
    pharmacies: dict[str, Pharmacy] = {}
    shifts: dict[tuple[str, date, str], DutyShift] = {}
    warnings: list[str] = []
    latest = None
    for file in files:
        filename = os.path.basename(file)
        with open(file, encoding="utf-8") as fh:
            data = json.load(fh)
        records = data.get("records", []) if isinstance(data, dict) else []
        p, s = _parse_records(records, filename, warnings)
        pharmacies.update(p)
        shifts.update(s)  # la descarga más reciente sobrescribe
        latest = _FILE_RE.search(file).group(1)
    if retrieved_at is None and latest:
        retrieved_at = datetime.strptime(latest, "%Y%m%d").replace(tzinfo=TZ)
    source = SourceInfo(
        source_id=SOURCE_ID,
        publisher=PUBLISHER,
        url=URL,
        license=LICENSE,
        retrieved_at=retrieved_at or datetime.now(TZ),
    )
    ordered = sorted(shifts.values(), key=lambda s: (s.start, s.pharmacy_id))
    return ParseResult(source, pharmacies, ordered, warnings)


# ---------------------------------------------------------------------------
# Capa oficial de farmacias (IDENA): DBF + conversión UTM 30N -> WGS84
# ---------------------------------------------------------------------------


def read_dbf(path: str, encoding: str = "latin-1") -> list[dict[str, str]]:
    """Lector mínimo de DBF (dBase III) con la librería estándar."""
    with open(path, "rb") as fh:
        header = fh.read(32)
        n_records, header_len, record_len = struct.unpack("<xxxxIHH20x", header)
        fields = []
        while True:
            desc = fh.read(32)
            if not desc or desc[0] == 0x0D:
                break
            name = desc[:11].split(b"\x00", 1)[0].decode("ascii")
            fields.append((name, desc[11:12].decode("ascii"), desc[16]))
        fh.seek(header_len)
        rows = []
        for _ in range(n_records):
            rec = fh.read(record_len)
            if not rec or rec[:1] == b"*":
                continue
            pos = 1
            row = {}
            for name, _ftype, length in fields:
                row[name] = rec[pos : pos + length].decode(encoding).strip()
                pos += length
            rows.append(row)
    return rows


def utm30n_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """ETRS89 / UTM 30N (EPSG:25830) a latitud/longitud (GRS80 ≈ WGS84 al cm)."""
    a = 6378137.0
    f = 1 / 298.257222101
    k0 = 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    x = easting - 500000.0
    m = northing / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
        + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
        + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
        + (1097 * e1 ** 4 / 512) * math.sin(8 * mu)
    )
    n1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    t1 = math.tan(phi1) ** 2
    c1 = ep2 * math.cos(phi1) ** 2
    r1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = x / (n1 * k0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (
        d ** 2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720
    )
    lon = (
        d
        - (1 + 2 * t1 + c1) * d ** 3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120
    ) / math.cos(phi1)
    return math.degrees(lat), -3.0 + math.degrees(lon)


def load_idena(dbf_path: str) -> dict[str, tuple[float, float]]:
    """Código de farmacia (F00242) -> (lat, lon) WGS84 según la capa IDENA."""
    out: dict[str, tuple[float, float]] = {}
    for row in read_dbf(dbf_path):
        code = row.get("IDFARMACIA", "")
        try:
            x, y = float(row["X25830"]), float(row["Y25830"])
        except (KeyError, ValueError):
            continue
        if code:
            out[code] = utm30n_to_wgs84(x, y)
    return out

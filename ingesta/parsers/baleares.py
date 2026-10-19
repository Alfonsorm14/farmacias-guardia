"""Parser de la fuente de Baleares (CAIB) para la campaña 2026.

Fuente: PDFs anuales, uno por zona, extraídos con `pdftotext -layout`
(una página = un día de una zona).

Uso:
    from ingesta.parsers.baleares import parse_dir
    result = parse_dir("data/raw/baleares/2026")
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import date, datetime, time, timedelta

from ingesta.common import TZ, normalize, pdf_bbox_pages, pdf_to_text
from ingesta.model import DutyShift, ParseResult, Pharmacy, SourceInfo

REGION = "04"
SOURCE_ID = "IB-CAIB-2026"
PUBLISHER = "Govern de les Illes Balears — Servei d'Ordenació Farmacèutica"
URL = "https://www.caib.es/sites/ordenaciofarmaceutica/es/guardias_ano_2026/"
LICENSE = "CC BY-SA (aviso legal caib.es)"

_HEADER_PREFIX = "Servei Farmac"
_DATE_RE = re.compile(r"^\w+,\s+(\d{1,2}) de (\w+) de (\d{4})$")
_FOOTER_RE = re.compile(
    r"^\d{2}/\d{2}/\d{4} - \d{2}/\d{2}/\d{4}\s+P.gina\s+\d+\s+de\s+\d+$"
)
_PHONE_RE = re.compile(r"(?<!\d)(\d{9})(?!\d)")
_SPLIT_RE = re.compile(r"(?<=\S)(\s{2,})(?=\S)")
# Hueco (pt) que como mínimo separa las columnas titular/dirección en el PDF;
# una palabra normal va precedida de ~2,5 pt (un espacio), así que 2+ espacios
# equivalen a un hueco amplio.
_COLUMN_GAP = 4.5
# Tolerancia (pt) al comparar el xMin de una palabra con la columna de dirección.
_COLUMN_TOLERANCE = 2.0
_TIMES_A_RE = re.compile(r"de\s+(\d{1,2}):(\d{2})\s+a\s+(\d{1,2}):(\d{2})", re.I)
_TIMES_PAREN_RE = re.compile(
    r"\(\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*\)"
)
_DUTY_RE = re.compile(r"\(\s*telf\.?\s*gu[aà]rdies?\s*(\d{9})\s*\)", re.I)

_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def pharmacy_id(holder: str, address: str, phone: str | None) -> str:
    """Identificador estable y reproducible de farmacia."""
    key = "|".join([normalize(holder), normalize(address), phone or ""])
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return "IB:" + digest


def parse_date_line(text: str) -> date | None:
    """Extrae la fecha de una línea 'jueves, 1 de enero de 2026'."""
    match = _DATE_RE.match(text.strip())
    if not match:
        return None
    day, month_name, year = match.group(1), match.group(2).lower(), match.group(3)
    month = _MONTHS.get(month_name)
    if month is None:
        return None
    return date(int(year), month, int(day))


def parse_shift_header(text: str) -> tuple[str, time, time] | None:
    """Interpreta una cabecera de turno.

    Devuelve (kind, hora_inicio, hora_fin) o None si no es una cabecera.
    """
    upper = text.upper()
    if "REFOR" in upper:
        kind = "refuerzo"
    elif "URG" in upper and "DIURN" in upper:
        kind = "diurna"
    elif "URG" in upper and "NOCTURN" in upper:
        kind = "nocturna"
    elif "URG" in upper:
        kind = "24h"
    else:
        return None

    match = _TIMES_A_RE.search(text)
    if match:
        start = time(int(match.group(1)), int(match.group(2)))
        end = time(int(match.group(3)), int(match.group(4)))
    else:
        match = _TIMES_PAREN_RE.search(text)
        if not match:
            return None
        start = time(int(match.group(1)), int(match.group(2)))
        end = time(int(match.group(3)), int(match.group(4)))
    return kind, start, end


def _extract_phone(line: str) -> tuple[str, str | None]:
    """Separa el teléfono final (último grupo de 9 dígitos) del resto."""
    matches = list(_PHONE_RE.finditer(line))
    if not matches:
        return line.rstrip(), None
    last = matches[-1]
    return line[: last.start()].rstrip(), last.group(1)


def _extract_duty_phone(text: str) -> tuple[str, str | None]:
    """Extrae y elimina el '( telf. guàrdies NNNNNNNNN )' de la línea."""
    match = _DUTY_RE.search(text)
    if not match:
        return text, None
    cleaned = text[: match.start()] + " " + text[match.end():]
    return cleaned, match.group(1)


def _extract_locality_legacy(
    address: str, tight_hyphen_is_address: bool = False
) -> tuple[str, str | None]:
    """Extrae la localidad final tras '-' si el patrón es claro.

    Con `tight_hyphen_is_address`, un guion pegado a alfanuméricos por ambos
    lados ("12-C'AS CONCOS") se considera parte de la dirección y no un
    separador de localidad. Solo lo usan las líneas reconstruidas por columnas
    (bbox), donde el texto se recompone sin los espacios originales del PDF.
    """
    for match in reversed(list(re.finditer(r"-\s*", address))):
        if (
            tight_hyphen_is_address
            and match.start() > 0
            and address[match.start() - 1].isalnum()
            and match.start() + 1 < len(address)
            and not address[match.start() + 1].isspace()
            and address[match.start() + 1].isalnum()
        ):
            continue
        locality = address[match.end():].strip("() ")
        if len(locality) < 3 or re.search(r"[0-9,]", locality):
            continue
        if not re.search(r"[^\W\d_]", locality, re.UNICODE):
            continue
        street = address[: match.start()].strip()
        if street:
            return street, locality
    return address.strip(), None


def _extract_locality(
    address: str, tight_hyphen_is_address: bool = False
) -> tuple[str, str | None]:
    """Extrae una localidad final y descarta los falsos positivos conocidos."""
    street, locality = _extract_locality_legacy(address, tight_hyphen_is_address)
    if locality is None:
        return street, None
    if locality.upper().startswith("URB."):
        return address.strip(), None
    if ". " in locality:
        locality = locality.rsplit(". ", 1)[1]
    if locality.count("(") > locality.count(")"):
        locality += ")" * (locality.count("(") - locality.count(")"))
    return street, locality


def split_holder_address(left: str) -> tuple[str, str, bool]:
    """Separa titular y dirección usando la columna dominante (2+ espacios).

    Devuelve (holder, address, ambiguous). Si no hay una separación clara
    (un solo espacio), marca ambiguous=True y conserva la línea completa en
    `address`, dejando en `holder` la parte segura (primer token).
    """
    match = _SPLIT_RE.search(left)
    if match:
        holder = left[: match.start()].strip()
        address = left[match.end():].strip()
        return holder, address, False
    first = left.split(None, 1)[0] if left.split() else ""
    return first, left.strip(), True


def make_shift(
    pharmacy_id: str,
    zone: str,
    day: date,
    kind: str,
    start: time,
    end: time,
    raw_label: str,
) -> DutyShift:
    """Construye un turno; si la hora de fin <= inicio, termina al día siguiente."""
    start_dt = datetime.combine(day, start).replace(tzinfo=TZ)
    end_day = day + timedelta(days=1) if end <= start else day
    end_dt = datetime.combine(end_day, end).replace(tzinfo=TZ)
    return DutyShift(
        pharmacy_id=pharmacy_id,
        zone=zone,
        start=start_dt,
        end=end_dt,
        kind=kind,
        raw_label=raw_label,
    )


def parse_pharmacy_line(
    line: str,
) -> tuple[Pharmacy, bool] | None:
    """Convierte una línea de farmacia en Pharmacy.

    Devuelve (pharmacy, ambiguous) o None si no hay teléfono.
    """
    left, phone = _extract_phone(line)
    if phone is None:
        return None
    left, duty_phone = _extract_duty_phone(left)
    holder, address, ambiguous = split_holder_address(left)
    legacy_address, _legacy_locality = _extract_locality_legacy(address)
    address, locality = _extract_locality(address)
    pharmacy = Pharmacy(
        id=pharmacy_id(holder, legacy_address, phone),
        region=REGION,
        holder=holder,
        address=address,
        locality=locality,
        postal_code=None,
        phone=phone,
        duty_phone=duty_phone,
    )
    return pharmacy, ambiguous


def _is_continuation(line: str) -> bool:
    if not line[:1].isspace():
        return False
    stripped = line.strip()
    if not stripped:
        return False
    if _PHONE_RE.search(line):
        return False
    upper = stripped.upper()
    if "URG" in upper or "REFOR" in upper:
        return False
    if _DATE_RE.match(stripped) or _FOOTER_RE.match(stripped):
        return False
    return True


def _merge_continuations(lines: list[str]) -> list[str]:
    """Une líneas de dirección partidas (p.ej. 'BLANES' tras 'COSTA D'EN')."""
    merged: list[str] = []
    for raw in lines:
        if (
            _is_continuation(raw)
            and merged
            and _PHONE_RE.search(merged[-1])
        ):
            merged[-1] = merged[-1].rstrip() + " " + raw.strip()
        else:
            merged.append(raw)
    return merged


def _pdf_bbox_pages(
    path: str,
) -> list[list[list[tuple[float, float, str]]]] | None:
    """Palabras con coordenadas por página (pdftotext -bbox-layout).

    Delega en `ingesta.common.pdf_bbox_pages` para compartir la extracción.
    """
    return pdf_bbox_pages(path)


def _page_column_x(rows: list[list[tuple[float, float, str]]]) -> float | None:
    """Calcula la X de inicio de la columna de dirección de una página.

    Usa la primera palabra tras el hueco amplio de cada línea de farmacia y
    toma la coordenada más frecuente (la columna es fija dentro de la página).
    """
    counts: dict[int, int] = {}
    for words in rows:
        if not any(_PHONE_RE.fullmatch(text) for _, _, text in words):
            continue
        for index in range(1, len(words)):
            gap = words[index][0] - words[index - 1][1]
            if gap >= _COLUMN_GAP and words[index][0] > 120:
                key = round(words[index][0])
                counts[key] = counts.get(key, 0) + 1
                break
    if not counts:
        return None
    return float(max(counts, key=lambda key: (counts[key], -key)))


def _resolve_ambiguous(
    pages: list[list[list[tuple[float, float, str]]]] | None,
    page: int,
    phone: str,
    cache: dict[int, float | None],
) -> tuple[str, str] | None:
    """Resuelve titular/dirección con las columnas del PDF (bbox).

    Devuelve (holder, address) o None si no se puede separar con seguridad.
    """
    if pages is None or not 1 <= page <= len(pages):
        return None
    if page not in cache:
        cache[page] = _page_column_x(pages[page - 1])
    column_x = cache[page]
    if column_x is None:
        return None
    for words in pages[page - 1]:
        if not any(text == phone for _, _, text in words):
            continue
        holder_words: list[str] = []
        address_words: list[str] = []
        for xmin, _xmax, text in words:
            if text == phone:
                continue
            if xmin >= column_x - _COLUMN_TOLERANCE:
                address_words.append(text)
            else:
                holder_words.append(text)
        if holder_words and address_words:
            return " ".join(holder_words), " ".join(address_words)
        return None
    return None


def _parse_file(path: str, source: SourceInfo) -> ParseResult:
    filename = os.path.basename(path)
    text = pdf_to_text(path)
    if text is None:
        return ParseResult(source, {}, [], [f"{filename}: SIN_TEXTO"])

    pharmacies: dict[str, Pharmacy] = {}
    shifts: list[DutyShift] = []
    warnings: list[str] = []

    zone: str | None = None
    day: date | None = None
    shift: tuple[str, time, time, str] | None = None
    expect_zone = False
    bbox_pages: list[list[list[tuple[float, float, str]]]] | None = None
    bbox_loaded = False
    column_cache: dict[int, float | None] = {}

    page_texts = text.replace("\r", "").split("\f")
    for page, raw_page in enumerate(page_texts, start=1):
        for raw in _merge_continuations(raw_page.split("\n")):
            stripped = raw.strip()
            if not stripped:
                continue

            if _HEADER_PREFIX in raw:
                expect_zone = True
                continue

            if expect_zone:
                zone = stripped
                expect_zone = False
                continue

            parsed_date = parse_date_line(stripped)
            if parsed_date is not None:
                day = parsed_date
                continue

            if _FOOTER_RE.match(stripped):
                continue

            header = parse_shift_header(stripped)
            if header is not None:
                kind, start, end = header
                shift = (kind, start, end, stripped)
                continue

            if _PHONE_RE.search(raw):
                parsed = parse_pharmacy_line(raw)
                if parsed is None:
                    warnings.append(
                        f"{filename} p{page}: LINEA_NO_RECONOCIDA: {stripped}"
                    )
                    continue
                pharmacy, ambiguous = parsed
                if ambiguous:
                    if not bbox_loaded:
                        bbox_pages = _pdf_bbox_pages(path)
                        bbox_loaded = True
                    resolved = _resolve_ambiguous(
                        bbox_pages, page, pharmacy.phone, column_cache
                    )
                    if resolved is not None:
                        holder, address = resolved
                        legacy_address, _legacy_locality = _extract_locality_legacy(
                            address, tight_hyphen_is_address=True
                        )
                        address, locality = _extract_locality(
                            address, tight_hyphen_is_address=True
                        )
                        pharmacy = Pharmacy(
                            id=pharmacy_id(holder, legacy_address, pharmacy.phone),
                            region=REGION,
                            holder=holder,
                            address=address,
                            locality=locality,
                            postal_code=None,
                            phone=pharmacy.phone,
                            duty_phone=pharmacy.duty_phone,
                        )
                        ambiguous = False
                if ambiguous:
                    warnings.append(
                        f"{filename} p{page}: LINEA_AMBIGUA: {stripped}"
                    )
                if zone is None or day is None or shift is None:
                    warnings.append(
                        f"{filename} p{page}: FARMACIA_SIN_TURNO: {stripped}"
                    )
                    continue
                pharmacies.setdefault(pharmacy.id, pharmacy)

                kind, start, end, raw_label = shift
                shifts.append(
                    make_shift(
                        pharmacy.id, zone, day, kind, start, end, raw_label
                    )
                )
                continue

            warnings.append(
                f"{filename} p{page}: LINEA_NO_RECONOCIDA: {stripped}"
            )

    return ParseResult(source, pharmacies, shifts, warnings)


def parse_dir(path: str, retrieved_at: datetime | None = None) -> ParseResult:
    """Procesa todos los PDF de un directorio y devuelve el resultado combinado."""
    source = SourceInfo(
        source_id=SOURCE_ID,
        publisher=PUBLISHER,
        url=URL,
        license=LICENSE,
        retrieved_at=retrieved_at or datetime.now(TZ),
    )

    pharmacies: dict[str, Pharmacy] = {}
    shifts: list[DutyShift] = []
    warnings: list[str] = []

    for filename in sorted(os.listdir(path)):
        if not filename.lower().endswith(".pdf"):
            continue
        result = _parse_file(os.path.join(path, filename), source)
        for pid, pharmacy in result.pharmacies.items():
            pharmacies.setdefault(pid, pharmacy)
        shifts.extend(result.shifts)
        warnings.extend(result.warnings)

    return ParseResult(source, pharmacies, shifts, warnings)


def parse_file(path: str, retrieved_at: datetime | None = None) -> ParseResult:
    """Procesa un único PDF (útil para tests y depuración)."""
    source = SourceInfo(
        source_id=SOURCE_ID,
        publisher=PUBLISHER,
        url=URL,
        license=LICENSE,
        retrieved_at=retrieved_at or datetime.now(TZ),
    )
    return _parse_file(path, source)

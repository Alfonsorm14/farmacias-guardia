"""Parser de la fuente de Murcia (BORM nº 301, 31/12/2025) para 2026.

Fuente: `data/raw/murcia/2026/BORM_2025_6468.pdf` (155 páginas con texto).
El Anexo III se extrae con `pdftotext -layout` y el Anexo II con
`pdftotext -bbox-layout` (posiciones estables por columna en todas las
páginas, a diferencia del texto con espacios que descuadra columnas).

Estructura del boletín:
- ANEXO I: descripción por agrupación (contexto). De aquí solo se extrae si
  una agrupación es "sistema localizado fuera del horario mínimo".
- ANEXO II: directorio de farmacias (tabla multilínea por columnas).
- ANEXO III: cuadrantes de guardia por agrupación.

Uso:
    from ingesta.parsers.murcia import parse
    result = parse("data/raw/murcia/2026/BORM_2025_6468.pdf")
"""
from __future__ import annotations

import os
from dataclasses import replace
import re
from datetime import date, datetime, time, timedelta

from ingesta.common import (
    TZ,
    digits_only,
    normalize,
    pdf_bbox_pages,
    pdf_to_text,
)
from ingesta.model import DutyShift, ParseResult, Pharmacy, SourceInfo

REGION = "14"
SOURCE_ID = "MU-BORM-2026"
PUBLISHER = (
    "Consejería de Salud de la Región de Murcia (BORM nº 301, 31/12/2025)"
)
URL = "https://www.borm.es/services/anuncio/ano/2025/numero/6468/pdf?id=840645"
LICENSE = "Acto administrativo publicado en diario oficial (art. 13 TRLPI)"

YEAR = 2026
_YEAR_DAYS = [
    date(YEAR, 1, 1) + timedelta(days=i) for i in range(365)
]

_PAGE_HEADER_RE = re.compile(r"N[uú]mero\s+301\b.*?P[aá]gina\s+(\d+)")
_FOOTER_RE = re.compile(r"^\s*(NPE:|D\.L\.)")
_AGRUPACION_I_RE = re.compile(
    r"^AGRUPACION(?:\s+FARMACEUTICA)?\s+(\d+)$"
)
_AGRUPACION_III_RE = re.compile(r"^AGRUPACION\s+(\d+)$")
_AGR_NAME_RE = re.compile(r"^\((.+)\)$")
_DATE_ROW_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})\s+(\d+)\s+(\S.*)$")
_ITEM_RE = re.compile(r"^(?:[-•]\s*)?MU\s*-?\s*(\d+)\b")
_LOCALIZADA_RE = re.compile(
    r"localizad\w*\s+fuera\s+del\s+horario\s+m", re.IGNORECASE
)
# Límites (xMin, en pt) de las columnas del Anexo II, derivados de la posición
# de la cabecera (ZONA/NOMBRE/Nº F/Nº TLFNO/DIRECCION/POBLACIÓN/C.P.) y
# verificados sobre todo el boletín: son estables en todas las páginas.
_II_BOUNDS = [0.0, 115.0, 222.0, 250.0, 310.0, 414.0, 476.0, 10 ** 9]
_II_COLUMNS = (
    "zone",
    "nombre",
    "numero",
    "tlfn",
    "direccion",
    "poblacion",
    "cp",
)
# Palabras que nunca cierran una celda: si el fragmento termina en una de
# ellas, el siguiente fragmento empieza palabra nueva (lleva espacio).
_II_CONNECTORS = {
    "DE", "DEL", "LA", "LAS", "LOS", "EL", "LO", "Y", "E", "SAN", "SANTA",
}
# Municipios de la provincia 30 según el INE (consulta: https://www.ine.es/dyngs/INEbase/es/operacion.htm?c=Estadistica_C&cid=1254736177011&menu=resultados&idp=1254734710990).
MURCIA_MUNICIPALITIES = (
    "ABANILLA", "ABARAN", "AGUILAS", "ALBUDEITE", "ALCANTARILLA",
    "LOS ALCAZARES", "ALEDO", "ALGUAZAS", "ALHAMA DE MURCIA", "ARCHENA",
    "BENIEL", "BLANCA", "BULLAS", "CALASPARRA", "CAMPOS DEL RIO",
    "CARAVACA DE LA CRUZ", "CARTAGENA", "CEHEGIN", "CEUTI", "CIEZA",
    "FORTUNA", "FUENTE ALAMO DE MURCIA", "JUMILLA", "LIBRILLA", "LORCA",
    "LORQUI", "MAZARRON", "MOLINA DE SEGURA", "MORATALLA", "MULA",
    "MURCIA", "OJOS", "PLIEGO", "PUERTO LUMBRERAS", "RICOTE", "SAN JAVIER",
    "SAN PEDRO DEL PINATAR", "SANTOMERA", "TORRE PACHECO",
    "LAS TORRES DE COTILLAS", "TOTANA", "ULEA", "LA UNION",
    "VILLANUEVA DEL RIO SEGURA", "YECLA",
)
_MUNICIPALITY_WORDS = frozenset(
    word for municipality in MURCIA_MUNICIPALITIES for word in municipality.split()
)
# Formas que aparecen completas en el Anexo II y que resuelven cortes de otra
# fila del mismo directorio.
_ANNEX_II_WHOLE_WORDS = frozenset({"ALMENDRICOS", "CALABARDINA"})
_REFERENCE_WORDS = _MUNICIPALITY_WORDS | _ANNEX_II_WHOLE_WORDS
# Glifos dañados por el PDF original; las sustituciones son inequívocas en la
# columna de población del Anexo II.
_LOCALITY_REPAIRS = {"CEUT�": "CEUTI", "PATI�O": "PATIÑO", "�ORA": "ÑORA"}


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_all_days(norm: str) -> bool:
    """True si la regla de días cubre todos los días del año."""
    if "TODOS LOS DIAS" not in norm:
        return False
    excluded = (
        "LUNES A SABADO",
        "LUNES A VIERNES",
        "LABORABLE",
        "SABADOS",
        "EXCLUIDOS",
    )
    return not any(token in norm for token in excluded)


def _is_rule_line(norm: str) -> bool:
    """True si la línea es una regla de días (p.ej. 'de lunes a sábado')."""
    if "TODOS LOS DIAS" in norm:
        return True
    if "LUNES A SABADO" in norm or "LUNES A VIERNES" in norm:
        return True
    if norm.startswith("DE LUNES") or norm.startswith("LABORABLE"):
        return True
    return "EXCLUID" in norm and "FESTIV" in norm


def _is_rotation(norm: str) -> bool:
    return norm.lstrip("(").startswith("ROTACION")


def _is_refuerzo_section(norm: str) -> bool:
    return norm.startswith("OTROS REFUERZO") or norm.startswith("REFUERZOS HASTA")


def _classify_header(norm: str) -> str | None:
    """Clasifica una posible cabecera de sección del Anexo III."""
    has_24 = "24 HORAS" in norm or "24 H" in norm or "24H" in norm
    has_922 = "9-22" in norm or "9 A 22" in norm
    all_days = "TODOS LOS DIAS" in norm and _is_all_days(norm)
    if has_24 and all_days:
        return "fixed24"
    if has_922 and all_days:
        return "refuerzo"
    if has_24:
        return "pending24"
    if has_922:
        return "pending_ref"
    return None


def _clean_lines(text: str) -> list[tuple[int, str]]:
    """Elimina cabecera/pie de página y devuelve (página, línea) por línea."""
    out: list[tuple[int, str]] = []
    page = 1
    for raw_page in text.replace("\r", "").split("\f"):
        for raw in raw_page.split("\n"):
            match = _PAGE_HEADER_RE.search(raw)
            if match:
                page = int(match.group(1))
                continue
            if _FOOTER_RE.match(raw):
                continue
            out.append((page, raw))
    return out


def _subzone_title(text: str) -> str:
    """Extrae el título de subzona, descartando descripciones largas."""
    title = text.strip().rstrip(":").strip()
    if "(" in title:
        head = title[: title.index("(")].strip()
        rest = title[title.index("("):]
        if head and len(rest) > 20:
            return head
    return title


def _full_day_shift(
    pharmacy_id: str, zone: str, day: date, kind: str, raw_label: str
) -> DutyShift:
    start = datetime.combine(day, time(0, 0), tzinfo=TZ)
    return DutyShift(
        pharmacy_id=pharmacy_id,
        zone=zone,
        start=start,
        end=start + timedelta(days=1),
        kind=kind,
        raw_label=raw_label,
        times_exact=False,
    )


def _refuerzo_shift(
    pharmacy_id: str, zone: str, day: date, raw_label: str
) -> DutyShift:
    return DutyShift(
        pharmacy_id=pharmacy_id,
        zone=zone,
        start=datetime.combine(day, time(9, 0), tzinfo=TZ),
        end=datetime.combine(day, time(22, 0), tzinfo=TZ),
        kind="refuerzo",
        raw_label=raw_label,
        times_exact=True,
    )


def _parse_anexo1(lines: list[tuple[int, str]]) -> set[int]:
    """Agrupaciones marcadas como 'sistema localizado fuera del horario'."""
    localizada: set[int] = set()
    current: int | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current is not None and _LOCALIZADA_RE.search(" ".join(buffer)):
            localizada.add(current)

    for _page, raw in lines:
        stripped = raw.strip()
        match = _AGRUPACION_I_RE.match(stripped)
        if match:
            flush()
            current = int(match.group(1))
            buffer = []
        elif current is not None:
            buffer.append(stripped)
    flush()
    return localizada


def _column_of(x: float) -> int:
    """Índice de la columna del Anexo II a la que pertenece una xMin (pt)."""
    for index in range(len(_II_BOUNDS) - 1):
        if _II_BOUNDS[index] <= x < _II_BOUNDS[index + 1]:
            return index
    return len(_II_BOUNDS) - 2


def _join_fragment(
    current: str, fragment: str, vocabulary: frozenset[str] = _REFERENCE_WORDS
) -> str:
    """Une un fragmento de celda respetando los saltos de línea del PDF.

    El boletín corta las palabras al llegar al ancho de columna, así que dos
    fragmentos consecutivos pueden ser la misma palabra (`ALCANTARIL`+`LA`) o
    dos palabras distintas (`ALHAMA DE`+`MURCIA`). Se decide por la última
    palabra del fragmento previo y la primera del nuevo.
    """
    if not current:
        return fragment
    if not fragment:
        return current
    last = current.split()[-1]
    first = fragment.split()[0]
    if last.endswith("-"):
        return current + fragment
    last_word_match = re.search(
        r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+(?=[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]*$)", last
    )
    first_word_match = re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", first)
    last_word = last_word_match.group(0) if last_word_match else ""
    first_word = first_word_match.group(0) if first_word_match else ""
    joined = normalize(last_word + first_word)
    joined_head = joined.split("-", 1)[0]
    if joined in vocabulary or joined_head in vocabulary:
        return current + fragment
    if " " not in fragment and len(first) <= 2 and len(last) >= 5:
        # Un fragmento de una o dos letras solo se pega si forma una palabra
        # conocida; de otro modo se conserva el separador que faltaba en el PDF.
        return current + " " + fragment
    return current + " " + fragment


def _anexo2_vocabulary(
    pages: list[list[list[tuple[float, float, str]]]], start: int, end: int
) -> frozenset[str]:
    """Palabras completas de las celdas del Anexo II y municipios oficiales."""
    words = set(_REFERENCE_WORDS)
    for page in pages[start:end]:
        for row in page:
            for _xmin, _xmax, text in row:
                words.update(normalize(word) for word in re.findall(r"[^\W\d_]+", text))
    return frozenset(words)


def _complete_locality(
    locality: str, vocabulary: frozenset[str], complete_words: frozenset[str] = frozenset()
) -> tuple[str, bool]:
    """Completa el último token de una población truncada por el ancho de columna.

    Un token es candidato a truncado si no es palabra conocida (`vocabulary`
    ni `complete_words`) y alguna palabra del vocabulario empieza por él. Se
    completa solo si la opción es única; si hay varias se devuelve ambiguo=True.
    """
    match = re.search(r"([^\W\d_]+)([^\w]*)$", locality, re.UNICODE)
    if match is None:
        return locality, False
    token = normalize(match.group(1))
    if token in vocabulary or token in complete_words:
        return locality, False
    matches = sorted(word for word in vocabulary if word.startswith(token))
    if len(matches) != 1:
        return locality, len(matches) > 1
    replacement = matches[0]
    return locality[: match.start(1)] + replacement + locality[match.end(1) :], False


def _anexo2_page_range(
    pages: list[list[list[tuple[float, float, str]]]],
) -> tuple[int, int] | None:
    """Rango de páginas del Anexo II (cabecera ZONA/NOMBRE hasta ANEXO III)."""
    start = end = None
    for position, rows in enumerate(pages):
        for words in rows:
            texts = [word[2] for word in words]
            if "ZONA" in texts and "NOMBRE" in texts:
                start = position
            if texts == ["ANEXO", "III"] and start is not None:
                end = position
                break
        if end is not None:
            break
    if start is None:
        return None
    return start, end if end is not None else len(pages)


def _parse_anexo2(
    pages: list[list[list[tuple[float, float, str]]]],
    filename: str,
    pharmacies: dict[str, Pharmacy],
    warnings: list[str],
) -> None:
    """Parsea la tabla multilínea del Anexo II usando coordenadas (bbox)."""
    span = _anexo2_page_range(pages)
    if span is None:
        return
    start, end = span
    vocabulary = _anexo2_vocabulary(pages, start, end)
    seen: dict[str, tuple[str, str, str | None]] = {}
    locality_pages: dict[str, int] = {}
    buffers: dict[str, list[str]] | None = None
    page_number = start + 1

    def cell(name: str) -> str:
        fragments = buffers[name] if buffers else []
        if name in ("numero", "tlfn", "cp"):
            return "".join(fragments)
        text = ""
        for fragment in fragments:
            text = _join_fragment(text, fragment, vocabulary)
        return text

    def flush() -> None:
        nonlocal buffers
        if buffers is None:
            return
        numero = digits_only(cell("numero"))
        if not numero:
            warnings.append(
                f"{filename} p{page_number}: FILA_SIN_NUMERO: "
                f"{_collapse(cell('nombre'))}"
            )
            buffers = None
            return
        pharmacy_id = "MU:" + str(int(numero))
        holder = _collapse(cell("nombre"))
        address = _collapse(cell("direccion"))
        locality = _collapse(cell("poblacion")) or None
        if locality:
            locality = _LOCALITY_REPAIRS.get(locality, locality)
        if locality:
            locality_pages[pharmacy_id] = page_number
        postal_code = digits_only(cell("cp")) or None
        phone = None
        raw_phone = digits_only(cell("tlfn"))
        match_phone = re.search(r"\d{9}", raw_phone)
        if match_phone:
            phone = match_phone.group(0)
        elif raw_phone:
            warnings.append(
                f"{filename} p{page_number}: TELEFONO_INVALIDO "
                f"{pharmacy_id}: {raw_phone}"
            )
        if not holder:
            warnings.append(
                f"{filename} p{page_number}: FARMACIA_SIN_NOMBRE: {pharmacy_id}"
            )
        signature = (normalize(holder), normalize(address), phone)
        if pharmacy_id in seen and seen[pharmacy_id] != signature:
            warnings.append(
                f"{filename} p{page_number}: FARMACIA_DUPLICADA {pharmacy_id}"
            )
        seen[pharmacy_id] = signature
        pharmacies[pharmacy_id] = Pharmacy(
            id=pharmacy_id,
            region=REGION,
            holder=holder,
            address=address,
            locality=locality,
            postal_code=postal_code,
            phone=phone,
            duty_phone=None,
        )
        buffers = None

    for position in range(start, end):
        page_number = position + 1
        for header in pages[position]:
            texts = [word[2] for word in header]
            if "Página" in texts:
                index = texts.index("Página")
                if index + 1 < len(texts) and texts[index + 1].isdigit():
                    page_number = int(texts[index + 1])
                break
        for words in pages[position]:
            texts = [word[2] for word in words]
            if (
                "Página" in texts
                or "Número" in texts
                or "A-311225-6468" in texts
                or (texts and texts[0].startswith("NPE"))
                or ("ZONA" in texts and "NOMBRE" in texts)
                or texts == ["ANEXO", "II"]
            ):
                continue
            cells: list[list[str]] = [[] for _ in _II_COLUMNS]
            for xmin, _xmax, text in words:
                cells[_column_of(xmin)].append(text)
            if re.fullmatch(r"\d+", " ".join(cells[0]).strip()):
                flush()
                buffers = {name: [] for name in _II_COLUMNS}
            if buffers is None:
                continue
            for name, values in zip(_II_COLUMNS[1:], cells[1:]):
                fragment = " ".join(values)
                if fragment:
                    buffers[name].append(fragment)
    flush()
    _complete_truncated_localities(
        filename, pharmacies, locality_pages, warnings
    )


def _completion_vocabulary(localities: list[str]) -> tuple[frozenset[str], frozenset[str]]:
    """Vocabulario para completar poblaciones truncadas del Anexo II.

    - `vocabulary`: municipios oficiales (INE), conectores y las palabras que no
      cierran su celda (solo la última palabra de una celda puede venir cortada
      por el ancho de columna, así que las demás son palabras completas).
    - `complete_words`: palabras que cierran la celda en dos o más farmacias; un
      corte por ancho de columna no se repite igual, así que se dan por completas.
    """
    words = set(_REFERENCE_WORDS) | _II_CONNECTORS
    final_counts: dict[str, int] = {}
    for locality in localities:
        tokens = [normalize(t) for t in re.findall(r"[^\W\d_]+", locality)]
        words.update(tokens[:-1])
        if tokens:
            final_counts[tokens[-1]] = final_counts.get(tokens[-1], 0) + 1
    complete = frozenset(word for word, count in final_counts.items() if count >= 2)
    return frozenset(words), complete


def _complete_truncated_localities(
    filename: str,
    pharmacies: dict[str, Pharmacy],
    locality_pages: dict[str, int],
    warnings: list[str],
) -> None:
    """Completa el último token de cada población del Anexo II si está truncado."""
    vocabulary, complete_words = _completion_vocabulary(
        [pharmacies[pid].locality for pid in locality_pages]
    )
    for pharmacy_id, page_number in locality_pages.items():
        pharmacy = pharmacies[pharmacy_id]
        locality, ambiguous = _complete_locality(
            pharmacy.locality, vocabulary, complete_words
        )
        if ambiguous:
            warnings.append(
                f"{filename} p{page_number}: POBLACION_TRUNCADA_AMBIGUA "
                f"{pharmacy_id}: {locality}"
            )
        if locality != pharmacy.locality:
            pharmacies[pharmacy_id] = replace(pharmacy, locality=locality)


def _parse_date_row(
    match: re.Match[str],
) -> date | None:
    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_block(
    agr_num: int,
    name: str | None,
    block: list[tuple[int, str]],
    filename: str,
    pharmacies: dict[str, Pharmacy],
    localizada: set[int],
    warnings: list[str],
) -> list[DutyShift]:
    """Procesa el bloque del Anexo III de una agrupación."""
    base_zone = (
        f"AGRUPACION {agr_num} ({name})" if name else f"AGRUPACION {agr_num}"
    )
    zone = base_zone
    zone_kind = "localizada" if agr_num in localizada else "24h"
    mode: str | None = None
    pending: tuple[str, str] | None = None
    header_label = base_zone
    shifts: list[DutyShift] = []
    zone_dates: dict[str, set[date]] = {base_zone: set()}

    def add_unknown(page: int, lines: list[str]) -> None:
        detail = " / ".join(lines[:2])
        warnings.append(
            f"{filename} p{page}: ANEXO_III_NO_SOPORTADO AGRUPACION "
            f"{agr_num}: {detail}"
        )

    def add_pharmacy_shifts(number: int, page: int) -> None:
        pharmacy_id = "MU:" + str(number)
        if pharmacy_id not in pharmacies:
            warnings.append(
                f"{filename} p{page}: ANEXO_III_FARMACIA_DESCONOCIDA "
                f"{pharmacy_id} ({base_zone})"
            )
            return
        if mode == "fixed24":
            for day in _YEAR_DAYS:
                shifts.append(
                    _full_day_shift(
                        pharmacy_id, zone, day, zone_kind, header_label
                    )
                )
        elif mode == "refuerzo":
            for day in _YEAR_DAYS:
                shifts.append(
                    _refuerzo_shift(pharmacy_id, zone, day, header_label)
                )

    index = 0
    previous_is_date = False
    unknown: list[str] = []
    unknown_page = 1

    def flush_unknown() -> None:
        nonlocal unknown
        if unknown:
            add_unknown(unknown_page, unknown)
        unknown = []

    while index < len(block):
        page, raw = block[index]
        stripped = raw.strip()
        if not stripped:
            flush_unknown()
            previous_is_date = False
            index += 1
            continue

        norm = normalize(stripped)

        date_match = _DATE_ROW_RE.match(stripped)
        if date_match:
            flush_unknown()
            day = _parse_date_row(date_match)
            number = int(date_match.group(4))
            pharmacy_id = "MU:" + str(number)
            if day is None:
                warnings.append(
                    f"{filename} p{page}: FECHA_INVALIDA: {stripped}"
                )
            elif pharmacy_id not in pharmacies:
                warnings.append(
                    f"{filename} p{page}: ANEXO_III_FARMACIA_DESCONOCIDA "
                    f"{pharmacy_id} ({zone})"
                )
            else:
                if day.year != YEAR:
                    warnings.append(
                        f"{filename} p{page}: FECHA_FUERA_DE_ANIO "
                        f"AGRUPACION {agr_num}: {stripped}"
                    )
                zone_dates.setdefault(zone, set()).add(day)
                shifts.append(
                    _full_day_shift(
                        pharmacy_id, zone, day, zone_kind, zone
                    )
                )
            previous_is_date = True
            index += 1
            continue

        if previous_is_date and not (
            _classify_header(norm) or _is_rule_line(norm)
        ):
            # Continuación del nombre de la fila de fecha anterior.
            previous_is_date = False
            index += 1
            continue
        previous_is_date = False

        # Título de subzona: seguido de filas diarias en las próximas líneas.
        if _looks_like_subzone(block, index):
            flush_unknown()
            subzone = _subzone_title(stripped)
            if subzone and subzone.upper() != (name or "").upper():
                zone = f"{base_zone} - {subzone}"
                zone_dates.setdefault(zone, set())
            index += 1
            # Consume las líneas de descripción de la subzona.
            while index < len(block):
                _p, _r = block[index]
                _s = _r.strip()
                if not _s or _DATE_ROW_RE.match(_s):
                    break
                if _classify_header(normalize(_s)) or _is_rule_line(
                    normalize(_s)
                ):
                    break
                index += 1
            continue

        header_kind = _classify_header(norm)
        if header_kind in ("fixed24", "refuerzo"):
            flush_unknown()
            mode = header_kind
            header_label = stripped
            pending = None
            index += 1
            continue
        if header_kind in ("pending24", "pending_ref"):
            flush_unknown()
            pending = (header_kind, stripped)
            mode = None
            index += 1
            continue

        if _is_refuerzo_section(norm) or norm.startswith("OTROS REFUERZO"):
            flush_unknown()
            add_unknown(page, [stripped])
            mode = "unsupported"
            pending = None
            index += 1
            continue

        if pending is not None:
            flush_unknown()
            pending_kind, pending_label = pending
            if _is_all_days(norm):
                mode = "fixed24" if pending_kind == "pending24" else "refuerzo"
                header_label = pending_label
            else:
                code = (
                    "REFUERZO_REGLA_NO_SOPORTADA"
                    if pending_kind == "pending_ref"
                    else "REGLA_24H_NO_SOPORTADA"
                )
                warnings.append(
                    f"{filename} p{page}: {code} AGRUPACION {agr_num}: "
                    f"{stripped}"
                )
                mode = "unsupported"
            pending = None
            index += 1
            continue

        if pending is None and mode in ("fixed24", "refuerzo") and _is_rule_line(
            norm
        ):
            flush_unknown()
            if _is_all_days(norm):
                index += 1
                continue
            warnings.append(
                f"{filename} p{page}: REFUERZO_REGLA_NO_SOPORTADA AGRUPACION "
                f"{agr_num}: {stripped}"
            )
            mode = "unsupported"
            index += 1
            continue

        item_match = _ITEM_RE.match(stripped)
        if item_match:
            if mode in ("fixed24", "refuerzo"):
                flush_unknown()
                add_pharmacy_shifts(int(item_match.group(1)), page)
            elif mode != "unsupported":
                flush_unknown()
                add_unknown(page, [stripped])
            index += 1
            continue

        if _is_rotation(norm):
            flush_unknown()
            if len(zone_dates.get(zone, set())) < 365:
                warnings.append(
                    f"{filename} p{page}: ROTACION_NO_SOPORTADA AGRUPACION "
                    f"{agr_num} [{zone}]: {stripped}"
                )
            index += 1
            # Consume las líneas de continuación de la nota.
            while index < len(block):
                _p, _r = block[index]
                if not _r.strip():
                    break
                index += 1
            continue

        if mode == "unsupported":
            index += 1
            continue

        if not unknown:
            unknown_page = page
        unknown.append(stripped)
        index += 1

    flush_unknown()
    return shifts


def _looks_like_subzone(block: list[tuple[int, str]], index: int) -> bool:
    """True si la línea inicia una subzona (título seguido de filas diarias)."""
    text = block[index][1].strip()
    if not text or _DATE_ROW_RE.match(text):
        return False
    # "(Rotación ..." partido por un salto de página es una regla, no una subzona
    # (Agrupación 14, Los Alcázares: el boletín repite la fila del 31/12 tras el salto).
    if text.startswith("("):
        return False
    first = next((c for c in text if c.isalpha()), "")
    if not first.isupper():
        return False
    seen = 0
    j = index + 1
    while j < len(block) and seen < 6:
        candidate = block[j][1].strip()
        if not candidate:
            j += 1
            continue
        if _DATE_ROW_RE.match(candidate):
            return True
        if _AGRUPACION_III_RE.match(candidate):
            return False
        if _is_rotation(normalize(candidate)):
            return False
        seen += 1
        j += 1
    return False


def _parse_anexo3(
    lines: list[tuple[int, str]],
    filename: str,
    pharmacies: dict[str, Pharmacy],
    localizada: set[int],
    warnings: list[str],
) -> list[DutyShift]:
    """Recorre el Anexo III, agrupación a agrupación, y genera turnos."""
    shifts: list[DutyShift] = []
    index = 0
    total = len(lines)
    while index < total:
        _page, raw = lines[index]
        stripped = raw.strip()
        match = _AGRUPACION_III_RE.match(stripped)
        if not match:
            index += 1
            continue
        agr_num = int(match.group(1))
        name: str | None = None
        if index + 1 < total:
            name_match = _AGR_NAME_RE.match(lines[index + 1][1].strip())
            if name_match:
                name = _collapse(name_match.group(1))
                index += 1
        block: list[tuple[int, str]] = []
        cursor = index + 1
        while cursor < total:
            candidate = lines[cursor][1].strip()
            if _AGRUPACION_III_RE.match(candidate):
                break
            block.append(lines[cursor])
            cursor += 1
        shifts.extend(
            _parse_block(
                agr_num,
                name,
                block,
                filename,
                pharmacies,
                localizada,
                warnings,
            )
        )
        index = cursor
    return shifts


def parse(pdf_path: str, retrieved_at: datetime | None = None) -> ParseResult:
    """Procesa el boletín de Murcia y devuelve el ParseResult combinado."""
    source = SourceInfo(
        source_id=SOURCE_ID,
        publisher=PUBLISHER,
        url=URL,
        license=LICENSE,
        # Fecha de descarga = última modificación del PDF (determinista entre ejecuciones).
        retrieved_at=retrieved_at or datetime.fromtimestamp(os.path.getmtime(pdf_path), TZ),
    )
    filename = os.path.basename(pdf_path)
    text = pdf_to_text(pdf_path)
    if text is None:
        return ParseResult(source, {}, [], [f"{filename}: SIN_TEXTO"])

    warnings: list[str] = []
    lines = _clean_lines(text)

    def find_heading(heading: str) -> int:
        for position, (_page, raw) in enumerate(lines):
            if raw.strip() == heading:
                return position
        return -1

    idx1 = find_heading("ANEXO I")
    idx3 = find_heading("ANEXO III")

    anexo1_end = find_heading("ANEXO II")
    if anexo1_end == -1:
        anexo1_end = len(lines)
    localizada = _parse_anexo1(
        lines[idx1 + 1:anexo1_end] if idx1 != -1 else []
    )

    pharmacies: dict[str, Pharmacy] = {}
    bbox_pages = pdf_bbox_pages(pdf_path)
    if bbox_pages is not None:
        _parse_anexo2(bbox_pages, filename, pharmacies, warnings)
    else:
        warnings.append(f"{filename}: ANEXO_II_SIN_COORDENADAS")

    shifts: list[DutyShift] = []
    if idx3 != -1:
        shifts = _parse_anexo3(
            lines[idx3 + 1:],
            filename,
            pharmacies,
            localizada,
            warnings,
        )

    # El boletín repite alguna fila tras un salto de página (31/12 de Los Alcázares): una vez.
    unique: dict[tuple, DutyShift] = {}
    for shift in shifts:
        unique.setdefault((shift.pharmacy_id, shift.zone, shift.start, shift.kind), shift)
    return ParseResult(source, pharmacies, list(unique.values()), warnings)

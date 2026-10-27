"""Importación declarativa de respuestas tabulares de transparencia.

Devuelve el contrato común sin descargar, completar ni extrapolar datos.
Véase docs/IMPORTADOR_GENERICO.md para el esquema YAML versión 1.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from ingesta.common import digits_only, normalize
from ingesta.model import DutyShift, ParseResult, Pharmacy, SourceInfo
from ingesta.parsers._tabular import InvalidCell, read_tables

FIELDS = {"holder", "address", "locality", "postal_code", "phone", "duty_phone", "code", "nif", "zone", "date", "start", "end", "slot", "kind"}
KINDS = {"diurna", "nocturna", "24h", "localizada", "refuerzo"}
OPERATIONS = {"strip", "spaces", "upper", "lower", "title", "digits", "normalize"}
UTC = timezone.utc


class MappingError(ValueError):
    """Configuración ausente, contradictoria o no admitida."""


class _UniqueLoader(yaml.SafeLoader):
    """No aceptar claves repetidas que oculten parte del mapeo."""


def _unique_mapping(loader, node):
    explicit = set()
    for key_node, value_node in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            continue
        key = loader.construct_object(key_node)
        if not isinstance(key, (str, int)) or key in explicit:
            raise MappingError(f"Clave YAML inválida o repetida en línea {key_node.start_mark.line + 1}")
        explicit.add(key)
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, (str, int)):
            raise MappingError(f"Clave YAML inválida en línea {key_node.start_mark.line + 1}")
        result[key] = loader.construct_object(value_node)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _object(value, allowed: set, where: str, required: set | None = None):
    if not isinstance(value, dict):
        raise MappingError(f"{where}: se esperaba un objeto")
    unknown = set(value) - allowed
    missing = (required or set()) - set(value)
    if unknown or missing:
        raise MappingError(f"{where}: claves desconocidas {sorted(unknown, key=str)}; faltan {sorted(missing)}")


def _positive(value, where):
    if type(value) is not int or value < 1:
        raise MappingError(f"{where}: debe ser un entero positivo (base uno)")


def _text(value, where):
    if not isinstance(value, str) or not value.strip():
        raise MappingError(f"{where}: debe ser texto no vacío; entrecomille códigos, fechas y horas")


def _column(value):
    if type(value) is int:
        _positive(value, "columna")
    else:
        _text(value, "columna")


def validate_mapping(mapping: dict) -> dict:
    """Valida el esquema sin abrir la entrada; rechaza erratas y opciones ignoradas."""
    _object(mapping, {"version", "source", "file", "columns", "defaults", "date_formats", "time_formats", "normalization", "values", "slots", "matrix", "ignore", "coverage"}, "mapeo", {"version", "source", "file", "columns", "date_formats", "time_formats"})
    if type(mapping["version"]) is not int or mapping["version"] != 1:
        raise MappingError("Versión de mapeo no admitida")
    source = mapping["source"]
    _object(source, {"source_id", "publisher", "url", "license", "region", "timezone", "id_prefix"}, "source", {"source_id", "publisher", "url", "license", "region", "timezone"})
    for key, value in source.items():
        _text(value, f"source.{key}")
    if not re.fullmatch(r"0[1-9]|1[0-9]", source["region"]):
        raise MappingError("source.region: se esperaba un código INE entre 01 y 19")
    try:
        ZoneInfo(source["timezone"])
    except ZoneInfoNotFoundError as exc:
        raise MappingError("Zona horaria desconocida") from exc
    config = mapping["file"]
    _object(config, {"type", "sheet", "pages", "header_row", "delimiter", "encoding", "column_starts"}, "file", {"type", "header_row"})
    kind = config["type"]
    if not isinstance(kind, str) or kind not in {"xlsx", "ods", "csv", "pdf"}:
        raise MappingError("file.type: use xlsx, ods, csv o pdf")
    _positive(config["header_row"], "file.header_row")
    specific = {"sheet": {"xlsx", "ods"}, "pages": {"pdf"}, "column_starts": {"pdf"}, "delimiter": {"csv"}, "encoding": {"csv"}}
    for key, kinds in specific.items():
        if key in config and kind not in kinds:
            raise MappingError(f"file.{key} no se aplica a {kind}")
    if "sheet" in config:
        _column(config["sheet"])
    if "pages" in config:
        pages = config["pages"]
        if not isinstance(pages, list) or not pages:
            raise MappingError("file.pages: lista no vacía de páginas")
        for page in pages:
            _positive(page, "file.pages")
        if len(set(pages)) != len(pages):
            raise MappingError("file.pages: páginas repetidas")
    if kind == "pdf":
        starts = config.get("column_starts")
        if not isinstance(starts, list) or not starts or starts[0] != 0 or any(type(n) is not int or n < 0 for n in starts) or starts != sorted(set(starts)):
            raise MappingError("file.column_starts: posiciones de carácter crecientes desde 0")
    if "delimiter" in config and (not isinstance(config["delimiter"], str) or len(config["delimiter"]) != 1):
        raise MappingError("file.delimiter: un solo carácter")
    if "encoding" in config:
        _text(config["encoding"], "file.encoding")
    columns, defaults = mapping["columns"], mapping.get("defaults", {})
    _object(columns, FIELDS, "columns")
    _object(defaults, FIELDS, "defaults")
    for field, col in columns.items():
        _column(col)
    for field, value in defaults.items():
        _text(value, f"defaults.{field}")
    supplied = set(columns) | set(defaults)
    required = {"holder", "address", "zone"}
    if "matrix" not in mapping:
        required.add("date")
    if not required <= supplied:
        raise MappingError(f"Faltan campos: {sorted(required - supplied)}")
    if "slot" in supplied and {"start", "end", "kind"} & supplied:
        raise MappingError("Use slot o start/end/kind; no mezcle ambos modos")
    if "matrix" not in mapping and "slot" not in supplied and not {"start", "end", "kind"} <= supplied:
        raise MappingError("Debe declarar slot o start/end/kind")
    for key in ("date_formats", "time_formats"):
        formats = mapping[key]
        if not isinstance(formats, list) or not formats:
            raise MappingError(f"{key}: lista no vacía de formatos strptime")
        for fmt in formats:
            _text(fmt, key)
            directives = set(re.findall(r"%([A-Za-z])", fmt.replace("%%", "")))
            if key == "date_formats" and not (
                ({"Y", "y"} & directives and ({"j"} <= directives or ({"m", "b", "B"} & directives and "d" in directives)))
                or {"G", "V", "u"} <= directives
            ):
                raise MappingError("date_formats: cada formato debe expresar una fecha completa, incluido el año")
            if key == "time_formats" and not ({"H", "I"} & directives):
                raise MappingError("time_formats: cada formato debe incluir la hora")
            if key == "time_formats" and "I" in directives and "p" not in directives:
                raise MappingError("time_formats: el reloj de 12 horas necesita %p")
    for key in ("normalization", "values"):
        _object(mapping.get(key, {}), FIELDS, key)
    for field, operations in mapping.get("normalization", {}).items():
        if not isinstance(operations, list) or any(not isinstance(op, str) or op not in OPERATIONS for op in operations):
            raise MappingError(f"normalization.{field}: operaciones desconocidas")
    for field, replacements in mapping.get("values", {}).items():
        if not isinstance(replacements, dict):
            raise MappingError(f"values.{field}: se esperaba un diccionario")
        for key, value in replacements.items():
            _text(key, "values.clave")
            _text(value, "values.valor")
    slots = mapping.get("slots", {})
    if not isinstance(slots, dict):
        raise MappingError("slots: se esperaba un diccionario")
    for label, slot in slots.items():
        _text(label, "slots.clave")
        _object(slot, {"start", "end", "kind"}, "slots", {"start", "end", "kind"})
        for key in ("start", "end", "kind"):
            _text(slot[key], f"slots.{label}.{key}")
        if slot["kind"] not in KINDS:
            raise MappingError(f"Tipo de guardia desconocido en slots.{label}")
        try:
            _clock(slot["start"], mapping, False)
            _clock(slot["end"], mapping, True)
        except ValueError as exc:
            raise MappingError(f"slots.{label}: {exc}") from exc
    if ("slot" in supplied or "matrix" in mapping) and not slots:
        raise MappingError("Debe declarar las franjas en slots")
    if "matrix" in mapping:
        if {"date", "slot", "start", "end", "kind"} & supplied:
            raise MappingError("La fecha y la franja de una matriz proceden de sus celdas")
        matrix = mapping["matrix"]
        _object(matrix, {"dates", "markers"}, "matrix", {"dates", "markers"})
        if not isinstance(matrix["dates"], list) or not matrix["dates"]:
            raise MappingError("matrix.dates: lista no vacía")
        seen = set()
        for item in matrix["dates"]:
            _object(item, {"column", "date"}, "matrix.dates", {"column", "date"})
            _column(item["column"])
            _text(item["date"], "matrix.date")
            if item["column"] in seen:
                raise MappingError("matrix.dates: columna repetida")
            seen.add(item["column"])
            try:
                _day(item["date"], mapping)
            except ValueError as exc:
                raise MappingError(f"matrix.date: {exc}") from exc
        if not isinstance(matrix["markers"], dict) or not matrix["markers"]:
            raise MappingError("matrix.markers: diccionario no vacío")
        for marker, slot in matrix["markers"].items():
            _text(marker, "matrix.marker")
            if not isinstance(slot, str) or slot not in slots:
                raise MappingError("matrix.markers: franja desconocida")
    ignore = mapping.get("ignore", {})
    _object(ignore, {"rows", "equals"}, "ignore")
    if not isinstance(ignore.get("rows", []), list):
        raise MappingError("ignore.rows: lista de números de fila")
    for number in ignore.get("rows", []):
        _positive(number, "ignore.rows")
    if not isinstance(ignore.get("equals", []), list):
        raise MappingError("ignore.equals: lista de reglas")
    for rule in ignore.get("equals", []):
        _object(rule, {"column", "value"}, "ignore.equals", {"column", "value"})
        _column(rule["column"])
        _text(rule["value"], "ignore.equals.value")
    coverage = mapping.get("coverage", {})
    _object(coverage, {"start", "end", "zones", "daily_start", "daily_end"}, "coverage")
    for pair in (("start", "end"), ("daily_start", "daily_end")):
        if any(k in coverage for k in pair) and not all(k in coverage for k in pair):
            raise MappingError(f"coverage: declare ambos {pair}")
    if "start" in coverage:
        try:
            start, end = (_day(coverage[key], mapping) for key in ("start", "end"))
            if end < start or (end - start).days > 3660:
                raise ValueError("Periodo invertido o superior a diez años")
        except (ValueError, TypeError) as exc:
            raise MappingError(f"coverage: {exc}") from exc
    if "daily_start" in coverage:
        try:
            _clock(coverage["daily_start"], mapping, False)
            _clock(coverage["daily_end"], mapping, True)
        except ValueError as exc:
            raise MappingError(f"coverage: {exc}") from exc
    if "zones" in coverage:
        if not isinstance(coverage["zones"], list) or not coverage["zones"]:
            raise MappingError("coverage.zones: lista no vacía")
        for zone in coverage["zones"]:
            _text(zone, "coverage.zones")
    return mapping


def load_mapping(path: Path | str) -> dict:
    """Carga YAML seguro, con claves únicas y esquema estricto."""
    try:
        with Path(path).open(encoding="utf-8") as stream:
            return validate_mapping(yaml.load(stream, Loader=_UniqueLoader))
    except yaml.YAMLError as exc:
        raise MappingError(f"YAML inválido: {exc}") from exc


def _string(value) -> str:
    if isinstance(value, InvalidCell):
        raise ValueError(value.reason)
    return "" if value is None else str(value).strip()


def _day(value, mapping) -> date:
    if isinstance(value, datetime):
        if value.time() != time() or value.tzinfo is not None:
            raise ValueError("La fecha contiene una hora o zona horaria no declarada")
        return value.date()
    for fmt in mapping["date_formats"]:
        try:
            return datetime.strptime(_string(value), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Fecha no reconocida: {_string(value)}")


def _clock(value, mapping, allow_24: bool) -> tuple[time, int]:
    if isinstance(value, datetime):
        value = value.time()
    if isinstance(value, timedelta):
        seconds = value.total_seconds()
        if seconds == 86400 and allow_24:
            return time(), 1
        if not 0 <= seconds < 86400 or seconds % 1:
            raise ValueError("Hora nativa fuera de rango")
        value = time(int(seconds // 3600), int(seconds % 3600 // 60), int(seconds % 60))
    if isinstance(value, time):
        if value.tzinfo:
            raise ValueError("La hora debe ser local sin offset")
        return value, 0
    text = _string(value)
    if allow_24 and text in {"24:00", "24:00:00"}:
        return time(), 1
    for fmt in mapping["time_formats"]:
        try:
            return datetime.strptime(text, fmt).time(), 0
        except ValueError:
            pass
    raise ValueError(f"Hora no reconocida: {text}")


def _local(naive: datetime, tz: ZoneInfo) -> datetime:
    valid = set()
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=tz, fold=fold)
        if candidate.astimezone(UTC).astimezone(tz).replace(tzinfo=None) == naive:
            valid.add(candidate.astimezone(UTC))
    if len(valid) != 1:
        raise ValueError(f"Hora local inexistente o ambigua por cambio horario: {naive.isoformat()}")
    return valid.pop().astimezone(tz)


def _interval(day, start_value, end_value, mapping):
    start_time, _ = _clock(start_value, mapping, False)
    end_time, offset = _clock(end_value, mapping, True)
    if not offset and end_time <= start_time:
        offset = 1
    tz = ZoneInfo(mapping["source"]["timezone"])
    start = _local(datetime.combine(day, start_time), tz)
    end = _local(datetime.combine(day + timedelta(days=offset), end_time), tz)
    if end.astimezone(UTC) <= start.astimezone(UTC):
        raise ValueError("El fin no es posterior al inicio")
    return start, end


def _normal(value, field, mapping):
    # Fechas y horas nativas se conservan para evitar conversiones conjeturales.
    if isinstance(value, (datetime, time, timedelta)):
        return value
    text = _string(value)
    for operation in mapping.get("normalization", {}).get(field, []):
        if operation == "spaces":
            text = re.sub(r"\s+", " ", text).strip()
        elif operation == "digits":
            text = digits_only(text)
        elif operation == "normalize":
            text = normalize(text)
        else:
            text = getattr(text, operation)()
    return mapping.get("values", {}).get(field, {}).get(text, text)


def _column_index(reference, headers):
    if type(reference) is int:
        index = reference - 1
        if index >= len(headers):
            raise ValueError(f"Columna fuera de la cabecera: {reference}")
        return index
    matches = [i for i, header in enumerate(headers) if _string(header) == reference]
    if len(matches) != 1:
        raise ValueError(f"Columna ausente o repetida: {reference}")
    return matches[0]


def parse_file(path: Path | str, mapping: dict | Path | str, retrieved_at: datetime | None = None) -> ParseResult:
    """Importa un fichero local y conserva los rechazos en warnings con su origen."""
    path = Path(path)
    mapping = validate_mapping(mapping) if isinstance(mapping, dict) else load_mapping(mapping)
    source = mapping["source"]
    tz = ZoneInfo(source["timezone"])
    retrieved_at = retrieved_at or datetime.fromtimestamp(path.stat().st_mtime, tz)
    if retrieved_at.tzinfo is None:
        raise ValueError("retrieved_at debe incluir zona horaria")
    result = ParseResult(SourceInfo(source["source_id"], source["publisher"], source["url"], source["license"], retrieved_at), {}, [], [])
    tables = read_tables(path, mapping["file"])
    seen = {}
    for table in tables:
        prefix = f"{path.name}, {table.label}"
        header_number = mapping["file"]["header_row"]
        headers = next((row for number, row in table.rows if number == header_number), None)
        if headers is None:
            result.warnings.append(f"{prefix}, fila {header_number}: ERROR: falta la cabecera")
            continue
        refs = list(mapping["columns"].values())
        refs += [r["column"] for r in mapping.get("ignore", {}).get("equals", [])]
        refs += [d["column"] for d in mapping.get("matrix", {}).get("dates", [])]
        try:
            indices = {ref: _column_index(ref, headers) for ref in refs}
        except ValueError as exc:
            result.warnings.append(f"{prefix}, fila {header_number}: ERROR: {exc}")
            continue
        for number, row in table.rows:
            if number <= header_number or number in mapping.get("ignore", {}).get("rows", []):
                continue
            where = f"{prefix}, fila {number}"
            def cell(ref):
                index = indices[ref]
                return row[index] if index < len(row) else ""
            try:
                if not any(isinstance(v, InvalidCell) or _string(v) for v in row):
                    continue
                if any(_string(cell(rule["column"])) == rule["value"] for rule in mapping.get("ignore", {}).get("equals", [])):
                    continue
                if len(row) > len(headers) and any(_string(v) for v in row[len(headers):]):
                    raise ValueError("Hay celdas fuera de la cabecera")
                values, raw_values, present = {}, {}, set()
                for field in FIELDS:
                    raw = cell(mapping["columns"][field]) if field in mapping["columns"] else ""
                    if raw is None or (isinstance(raw, str) and not raw.strip()):
                        raw = mapping.get("defaults", {}).get(field, "")
                    if raw is not None and raw != "":
                        present.add(field)
                    if isinstance(raw, (datetime, time, timedelta)) and field not in {"date", "start", "end"}:
                        raise ValueError(f"Tipo de celda nativo incompatible con {field}")
                    raw_values[field] = raw
                    values[field] = _normal(raw, field, mapping)
                for field in ("holder", "address", "zone"):
                    if not values[field]:
                        raise ValueError(f"Campo obligatorio vacío: {field}")
                for field, pattern in (("postal_code", r"\d{5}"), ("phone", r"\d{9}"), ("duty_phone", r"\d{9}")):
                    if field in present and not re.fullmatch(pattern, values[field]):
                        result.warnings.append(f"{where}: AVISO: {field} inválido; se conserva como ausente")
                        values[field] = ""
                key = values["code"] or values["nif"]
                if not key:
                    identity = json.dumps([values[k] for k in ("holder", "address", "locality", "postal_code")], ensure_ascii=False)
                    key = "derived-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
                pid = source.get("id_prefix", source["source_id"]) + ":" + key
                pharmacy = Pharmacy(pid, source["region"], values["holder"], values["address"], values["locality"] or None, values["postal_code"] or None, values["phone"] or None, values["duty_phone"] or None)
                if pid in result.pharmacies and result.pharmacies[pid] != pharmacy:
                    raise ValueError(f"Datos contradictorios para la farmacia {pid}; no se sobrescriben")
                candidates = []
                if "matrix" in mapping:
                    matrix = mapping["matrix"]
                    for entry in matrix["dates"]:
                        marker = _string(cell(entry["column"]))
                        if marker:
                            candidates.append((entry["date"], matrix["markers"].get(marker), marker, entry["column"]))
                else:
                    candidates = [(values["date"], values["slot"], _string(raw_values["slot"]), None)]
                for day_value, slot_label, raw_label, column in candidates:
                    origin = where + (f", columna {column}" if column is not None else "")
                    try:
                        day = _day(day_value, mapping)
                        if "matrix" in mapping or "slot" in mapping["columns"] or "slot" in mapping.get("defaults", {}):
                            if slot_label not in mapping.get("slots", {}):
                                raise ValueError(f"Franja o marca desconocida: {raw_label}")
                            slot = mapping["slots"][slot_label]
                            start_value, end_value, kind = slot["start"], slot["end"], slot["kind"]
                        else:
                            start_value, end_value, kind = (values[k] for k in ("start", "end", "kind"))
                            raw_label = f"{_string(start_value)} - {_string(end_value)}"
                        if kind not in KINDS:
                            raise ValueError(f"Tipo de guardia desconocido: {kind}")
                        start, end = _interval(day, start_value, end_value, mapping)
                        shift = DutyShift(pid, values["zone"], start, end, kind, raw_label)
                        shift_key = (pid, shift.zone, start.astimezone(UTC), kind)
                        if shift_key in seen:
                            previous, previous_origin = seen[shift_key]
                            label = "Turno duplicado" if previous.end == end else "Turnos contradictorios con el mismo inicio y tipo"
                            raise ValueError(f"{label}; primera aparición en {previous_origin}")
                        seen[shift_key] = shift, origin
                        result.pharmacies[pid] = pharmacy
                        result.shifts.append(shift)
                    except ValueError as exc:
                        result.warnings.append(f"{origin}: ERROR: {exc}")
            except ValueError as exc:
                result.warnings.append(f"{where}: ERROR: {exc}")
    if not result.shifts:
        result.warnings.append(f"{path.name}: ERROR: no hay turnos válidos")
    return result


def coverage_report(result: ParseResult, mapping: dict) -> dict:
    """Cobertura real por fecha/zona; nunca genera turnos para cubrir los huecos.

    Sin periodo explícito se limita al intervalo observado. Las horas sin
    servicio solo se consideran huecos cuando se declara una ventana diaria.
    """
    config = mapping.get("coverage", {})
    tz = ZoneInfo(mapping["source"]["timezone"])
    dates = [s.start.astimezone(tz).date() for s in result.shifts]
    dates += [(s.end.astimezone(tz) - timedelta(microseconds=1)).date() for s in result.shifts]
    zones = sorted(set(config.get("zones", [])) | {s.zone for s in result.shifts})
    if "start" in config:
        first, last = (_day(config[key], mapping) for key in ("start", "end"))
    elif dates:
        first, last = min(dates), max(dates)
    else:
        return {"scope": "observed", "daily": [], "gaps": []}
    if (last - first).days > 3660:
        raise ValueError("El intervalo de cobertura supera diez años; declare un periodo acotado")
    daily, gaps = [], []
    day = first
    while day <= last:
        if "daily_start" in config:
            start, end = _interval(day, config["daily_start"], config["daily_end"], mapping)
        else:
            start = _local(datetime.combine(day, time()), tz)
            end = _local(datetime.combine(day + timedelta(days=1), time()), tz)
        start_utc, end_utc = start.astimezone(UTC), end.astimezone(UTC)
        for zone in zones:
            shifts = [s for s in result.shifts if s.zone == zone and s.start.astimezone(UTC) < end_utc and s.end.astimezone(UTC) > start_utc]
            daily.append({"date": day.isoformat(), "zone": zone, "shifts": len(shifts), "pharmacies": len({s.pharmacy_id for s in shifts})})
            if "daily_start" not in config:
                if not shifts:
                    gaps.append({"date": day.isoformat(), "zone": zone})
            else:
                cursor = start_utc
                intervals = sorted((max(start_utc, s.start.astimezone(UTC)), min(end_utc, s.end.astimezone(UTC))) for s in shifts)
                for left, right in intervals + [(end_utc, end_utc)]:
                    if left > cursor:
                        gaps.append({"date": day.isoformat(), "zone": zone, "start": cursor.astimezone(tz).isoformat(), "end": left.astimezone(tz).isoformat()})
                    cursor = max(cursor, right)
        day += timedelta(days=1)
    return {"scope": "declared" if "start" in config else "observed", "start": first.isoformat(), "end": last.isoformat(), "daily": daily, "gaps": gaps}

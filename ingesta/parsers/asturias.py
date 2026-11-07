"""Buscador GESCOF del COF de Asturias. Solo asignaciones diarias publicadas.

HTML y protocolo contrastados en docs/FUENTE_asturias.md. Sin extrapolaciones.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from pathlib import Path

from ingesta.common import TZ
from ingesta.model import DutyShift, ParseResult, Pharmacy, SourceInfo

SOURCE_ID = "AS-COF-GESCOF"
URL = "https://www.farmasturias.org/GESCOF/cms/Guardias/FarmaciaBuscar.asp?IdMenu=111"
POST_URL = URL + "&intPagina=1"
LICENSE = "Reutilización pendiente de autorización del titular; solo revisión local"
MONTHS = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()
CONDITIONAL_HOURS = ("09:30 - 22:00", "Lunes a sábado de 9,30 de la mañana a 10 de la noche. Domingos y festivos: de 10 de la mañana a 10 de la noche")
# Parejas contrastadas en las capturas: un name horario por sí solo puede ser
# engañoso (por ejemplo, la cabecera semanal también utiliza 09:00 - 09:00).
KNOWN_HOURS = {
    ("00:00 - 00:00", "Guardia no presencial"),
    ("00:00 - 00:00", "Las 24 horas"),
    ("09:00 - 09:00", "De 9 de la mañana de hoy a 9 de la mañana de mañana"),
    ("09:25 - 09:25", "De 9,25 de la mañana de hoy a 9,25 de la mañana de mañana"),
    ("09:30 - 09:30", "De 9,30 de la mañana de hoy a 9,30 de la mañana de mañana"),
    ("09:30 - 22:00", "De 9,30 horas a 10 de la noche"),
    ("09:00 - 22:00", "De 9 a 22 horas"),
    ("00:00 - 09:30", "Desde las 10 de la noche de ayer a las 9,30 horas de hoy"),
    ("22:00 - 09:30", "Desde las 10 de la noche de hoy a las 9,30 horas de mañana"),
}


def clean(value: str) -> str:
    return " ".join(value.split())


class SearchHTML(HTMLParser):
    """Lee los encabezados y fichas reales; no ejecuta los enlaces JavaScript."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.context = {}
        self.capture = None
        self.parts = []
        self.row = None
        self.row_text = []
        self.options = {"txtMunicipio": [], "txtLocalidad": []}
        self.select = None
        self.option = None
        self.form = False
        self.closed_form = False
        self.input_date = None
        self.day = None
        self.pagination = []
        self.result_lists = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        if self.form and not self.closed_form:
            # Un encabezado nuevo, incluso si cambia de clase, cierra el ámbito
            # anterior. Nunca reutilizar por accidente su concejo u horario.
            if tag == "h4":
                self.context.clear()
            elif tag == "h5":
                for key in ("clock", "HorarioGuardias", "LocalidadGuardias"):
                    self.context.pop(key, None)
            elif tag == "h6":
                self.context.pop("LocalidadGuardias", None)
        if tag == "ul" and cls == "ListadoResultados":
            self.result_lists += 1
        if tag == "form" and a.get("name") == "formulario":
            self.form = a.get("method", "").lower() == "post" and a.get("action") == "FarmaciaBuscar.asp?IdMenu=111&intPagina=1"
        if tag == "input" and a.get("name") == "Fecha":
            self.input_date = a.get("value")
        if tag == "select":
            self.select = a.get("name")
        if tag == "option":
            self.option = a.get("value", "")
            self.capture, self.parts = ("option", tag), []
        if cls in ("FechaGuardias", "MunicipioGuardias", "HorarioGuardias", "LocalidadGuardias"):
            self.capture, self.parts = (cls, tag), []
        if tag == "a" and self.capture and self.capture[0] == "HorarioGuardias":
            self.context["clock"] = a.get("name", "")
        if tag == "a" and "intPagina=" in a.get("href", ""):
            self.pagination.append(a["href"])
        if tag == "li":
            self.row, self.row_text = dict(self.context), []
            self.row["line"] = self.getpos()[0]
        if tag == "span" and cls in ("TituloResultado", "ico-localizacion", "ico-telefono", "ico-buscador2"):
            self.capture, self.parts = (cls, tag), []

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)
        if self.row is not None:
            self.row_text.append(data)

    def handle_endtag(self, tag):
        if self.capture and self.capture[1] == tag:
            key = self.capture[0]
            value = clean("".join(self.parts))
            if key == "option" and self.select in self.options and self.option:
                self.options[self.select].append((self.option, value))
            elif key == "FechaGuardias":
                m = re.search(r"(\d{2}) de (\w+) de (\d{4})", value.lower())
                if m:
                    self.day = date(int(m[3]), MONTHS.index(m[2]) + 1, int(m[1]))
            elif key in ("MunicipioGuardias", "HorarioGuardias", "LocalidadGuardias"):
                self.context[key] = value
                if key == "MunicipioGuardias":
                    self.context.pop("HorarioGuardias", None)
                    self.context.pop("LocalidadGuardias", None)
            elif self.row is not None:
                self.row[key] = value
            self.capture = None
        if tag == "li" and self.row is not None:
            if "TituloResultado" in self.row:
                self.row["text"] = clean(" ".join(self.row_text))
                self.rows.append(self.row)
            self.row = None
        if tag == "select":
            self.select = None
        if tag == "form" and self.form:
            self.closed_form = True


def inspect_html(data: bytes, requested: date) -> SearchHTML:
    # La plantilla tiene bytes no UTF-8 en menús ajenos a las fichas. Las fichas sí
    # son UTF-8; se rechaza cualquier campo de resultado con pérdida de caracteres.
    page = SearchHTML()
    page.feed(data.decode("utf-8", errors="replace"))
    if not page.form or not page.closed_form or page.input_date != requested.strftime("%d/%m/%Y"):
        raise ValueError("Respuesta GESCOF incompleta o formulario/fecha inesperados")
    if page.pagination:
        raise ValueError("Paginación nueva: inspeccionar antes de continuar")
    if page.result_lists != len(page.rows):
        raise ValueError("Ficha sin título reconocido: revisar estructura")
    if page.rows and page.day != requested:
        raise ValueError("La fecha de resultados no coincide con la solicitada")
    if not page.rows and page.day is not None:
        raise ValueError("Cabecera de resultados sin fichas: revisar estructura")
    return page


def _interval(row: dict, day: date):
    label = row.get("HorarioGuardias", "")
    clock = row.get("clock", "")
    m = re.fullmatch(r"(\d{2}):(\d{2}) - (\d{2}):(\d{2})", clock)
    if not m:
        raise ValueError("horario sin intervalo legible")
    h1, m1, h2, m2 = map(int, m.groups())
    low = label.lower()
    # Una semana descrita no autoriza a crear los otros seis días. El intervalo
    # 09-09 no es diario en este caso: se omite con aviso, sin inventar su inicio.
    if "viernes siguiente" in low:
        raise ValueError("horario semanal sin fechas de extremos; no se proyecta")
    if "domingos y festivos" in low:
        if (clock, label) == CONDITIONAL_HOURS and day.weekday() == 6:
            # El domingo no requiere conocer fiestas locales: ambas condiciones
            # publicadas conducen al mismo horario explícito de 10 a 22 horas.
            return (datetime.combine(day, time(10), TZ),
                    datetime.combine(day, time(22), TZ), "diurna")
        raise ValueError("horario condicionado a festivos sin calendario publicado")
    if not label or "\ufffd" in label:
        raise ValueError("cabecera ausente o codificación inválida")
    if (clock, label) not in KNOWN_HOURS:
        raise ValueError("horario nuevo sin inspeccionar; no se genera el turno")
    start = datetime.combine(day, time(h1, m1), TZ)
    end = datetime.combine(day, time(h2, m2), TZ)
    if "de ayer" in low:
        # En esta cabecera real el atributo name dice 00:00; manda el texto.
        if label != "Desde las 10 de la noche de ayer a las 9,30 horas de hoy":
            raise ValueError("horario de ayer no reconocido")
        start = datetime.combine(day - timedelta(days=1), time(22), TZ)
    elif end <= start:
        end += timedelta(days=1)
    if "no presencial" in low:
        kind = "localizada"
    elif end - start == timedelta(days=1):
        kind = "24h"
    elif start.hour >= 21 or "de ayer" in low:
        kind = "nocturna"
    else:
        kind = "diurna"
    return start, end, kind


def parse_html(data: bytes, requested: date, *, filename: str = "respuesta.html",
               retrieved_at: datetime | None = None) -> ParseResult:
    page = inspect_html(data, requested)
    result = ParseResult(SourceInfo(SOURCE_ID,
        "Colegio Oficial de Farmacéuticos del Principado de Asturias", URL, LICENSE,
        retrieved_at or datetime.now(TZ)), {}, [], [])
    for row in page.rows:
        location = f"{filename}:página 1:línea {row['line']}"
        try:
            number = re.fullmatch(r"Nº Farmacia:\s*(\d+)", row.get("ico-buscador2", ""))
            if not number:
                raise ValueError("número de farmacia ausente")
            pid = "AS:" + number[1]
            address = row.get("ico-localizacion", "").removeprefix("Dirección:").strip()
            holder = row["TituloResultado"]
            locality = row.get("LocalidadGuardias")
            zone = row.get("MunicipioGuardias")
            if not address or not holder or not zone or any("\ufffd" in v for v in (address, holder, locality or "", zone)):
                raise ValueError("ficha incompleta o codificación inválida")
            cp = re.search(r"-(\d{5})$", address)
            phone_text = row.get("ico-telefono", "").removeprefix("Teléfono:").strip()
            phone = re.sub(r"\D", "", phone_text)
            if len(phone) != 9:
                phone = None
                result.warnings.append(f"{location}: {pid}: teléfono ausente o inválido")
            duty = re.search(r"(?:llamar al|teléfono)\s+(\d{9})\b", row["text"])
            if not locality or not cp:
                result.warnings.append(f"{location}: {pid}: localidad o código postal ausente")
            result.pharmacies[pid] = Pharmacy(pid, "03", holder, address, locality,
                cp[1] if cp else None, phone, duty[1] if duty else None)
            start, end, kind = _interval(row, requested)
            result.shifts.append(DutyShift(pid, zone, start, end, kind, row["HorarioGuardias"]))
        except ValueError as exc:
            result.warnings.append(f"{location}: {row['TituloResultado']}: {exc}")
    if not page.rows:
        result.warnings.append(f"{filename}:página 1: SIN_DATOS para {requested}; no implica ausencia de guardia")
    return result


def parse_dir(directory: str | Path) -> ParseResult:
    """Última respuesta por fecha; reemplaza el día completo tras intercambios."""
    result = ParseResult(SourceInfo(SOURCE_ID,
        "Colegio Oficial de Farmacéuticos del Principado de Asturias", URL, LICENSE,
        datetime.now(TZ)), {}, [], [])
    groups = {}
    for path in sorted(Path(directory).glob("????-??-??.html"), key=lambda p: (p.stat().st_mtime, p.name)):
        day = date.fromisoformat(path.stem)
        parsed = parse_html(path.read_bytes(), day, filename=str(path),
                            retrieved_at=datetime.fromtimestamp(path.stat().st_mtime, TZ))
        result.pharmacies.update(parsed.pharmacies)
        result.warnings.extend(parsed.warnings)
        daily = {}
        for shift in parsed.shifts:
            key = (shift.zone, shift.start, shift.end, shift.kind)
            daily.setdefault(key, set()).add(shift)
        # La noche puede aparecer como «hoy» y como «ayer» en días contiguos.
        # Si cambia la asignación, manda el grupo completo observado más tarde.
        groups.update(daily)
        result.source = parsed.source
    result.shifts = sorted((s for shifts in groups.values() for s in shifts),
                           key=lambda s: (s.start, s.zone, s.pharmacy_id, s.raw_label))
    return result

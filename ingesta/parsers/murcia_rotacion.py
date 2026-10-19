"""Propuesta (NO activada): proyección de las rotaciones del Plan de Urgencias de Murcia 2026.

El Anexo III del BORM nº 301 (31/12/2025) publica, para la mayoría de agrupaciones, solo el
cuadrante de enero y una regla del tipo "Rotación por días, de modo sucesivo según el orden
expuesto, hasta 31/12/2026". El proyecto, por regla (docs/SPEC.md), no deduce turnos: hoy esas
agrupaciones muestran "Sin datos oficiales para esta fecha" desde febrero.

Este módulo calcula, solo para decisión de Alfonso, qué turnos resultarían de aplicar la regla
publicada y con qué garantías. No se importa por defecto: el resultado va a data/propuestas/.

Criterios conservadores (cualquier duda -> la agrupación no se proyecta):
- La regla del Anexo III no puede tener condiciones que el cuadrante de enero no reproduzca
  (saltos, régimen especial de festivos, turnos dobles, fines de semana a cargo de otra farmacia,
  excepciones de verano...).
- El cuadrante de enero debe ser periódico y el ciclo debe quedar determinado:
  * rotación diaria: el ciclo completo se ve al menos dos veces en enero;
  * rotación semanal: bloques de 7 días y todas las farmacias de la agrupación vistas en orden.
- Las vacaciones del Anexo I no dicen quién sustituye: esos días se dejan sin turno.
- Fechas ya publicadas explícitamente (p. ej. "Cambios de verano" de Yecla) no se tocan.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
YEAR_END = date(2026, 12, 31)

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

# Condiciones de la regla que un ciclo simple no reproduce.
CONDICIONES_BLOQUEANTES = (
    "salto", "librando", "régimen especial", "regimen especial", "turno doble", "verano",
    "correspondiendo", "realizando el turno del domingo", "distinguiendo", "fin de semana",
    "turno continúo viernes", "turno continuo viernes", "excepto", "festivos",
)

_AGR_RE = re.compile(r"^\s*AGRUPACI[OÓ]N(?:\s+FARMAC\w*)?\s+(\d+)\s*$")
_DATE_ROW_RE = re.compile(r"^\s*\d{2}/\d{2}/\d{4}\s")
_SECTION_RE = re.compile(r"^\s*[A-Z]\)\s")
_NOISE_RE = re.compile(r"NPE:|N[uú]mero\s+301|D\.L\.\s+MU")
_CODE_RE = re.compile(r"MU\s*-?\s*(\d+)")


@dataclass
class Evaluacion:
    zona: str
    agrupacion: int | None
    regla: str
    dias: int
    farmacias: int
    periodo: int | None
    tipo: str | None  # "diaria" | "semanal"
    motivo: str | None  # None = proyectable
    vacaciones: dict[str, list[date]] = field(default_factory=dict)

    @property
    def proyectable(self) -> bool:
        return self.motivo is None


def _clean_lines(text: str) -> list[str]:
    return [line for line in text.split("\n") if not _NOISE_RE.search(line)]


def split_annexes(text: str) -> tuple[list[str], list[str]]:
    """(líneas del Anexo I, líneas del Anexo III)."""
    lines = _clean_lines(text)
    idx_ii = next(i for i, l in enumerate(lines) if l.strip() == "ANEXO II")
    idx_iii = next(i for i, l in enumerate(lines) if l.strip() == "ANEXO III")
    idx_i = next(i for i, l in enumerate(lines) if l.strip() == "ANEXO I")
    return lines[idx_i:idx_ii], lines[idx_iii:]


def rule_texts(anexo_iii: list[str]) -> dict[int, str]:
    """Texto de cada agrupación del Anexo III, sin las filas de fechas."""
    out: dict[int, list[str]] = {}
    cur = None
    for line in anexo_iii:
        m = _AGR_RE.match(line)
        if m:
            cur = int(m.group(1))
            out.setdefault(cur, [])
            continue
        if cur is None or not line.strip() or _DATE_ROW_RE.match(line):
            continue
        out[cur].append(line.strip())
    return {k: re.sub(r"\s+", " ", " ".join(v)) for k, v in out.items()}


def _parse_dates(texto: str, year: int = 2026) -> tuple[list[date], str]:
    """Fechas de un texto de vacaciones. Devuelve (fechas, resto no interpretado)."""
    fechas: list[date] = []
    t = texto.lower().replace("º", "").replace(" ", " ")
    t = re.sub(r"\b(?:(?:de|del)\s+)?\d{4}\b", " ", t)  # "de 2026", "agosto 2026"
    t = re.sub(r"\b0(\d)\b", r"\1", t)
    mes = "|".join(MESES)
    # "del 14 al 16 y del 22 al 23 de agosto": el primer rango toma el mes que viene después.
    def completar_mes(m: re.Match) -> str:
        siguiente = re.search(rf"\b({mes})\b", t[m.end():])
        return f"{m.group(0)} de {siguiente.group(1)}" if siguiente else m.group(0)
    t = re.sub(rf"\b\d{{1,2}}\s+al\s+\d{{1,2}}\b(?!\s+(?:de\s+)?(?:{mes}))", completar_mes, t)

    def rango(d1: int, m1: int, d2: int, m2: int) -> None:
        a, b = date(year, m1, d1), date(year, m2, d2)
        if b < a:
            raise ValueError(f"rango invertido {a} {b}")
        fechas.extend(a + timedelta(days=i) for i in range((b - a).days + 1))

    # "del 1 al 16 de agosto", "del 17 de agosto al 2 septiembre", "13 de julio al 2 de agosto"
    pat = re.compile(rf"(?:del\s+)?(\d{{1,2}})(?:\s+de)?(?:\s+({mes}))?\s+al\s+(\d{{1,2}})(?:\s+de)?\s+({mes})")
    def sub_rango(m: re.Match) -> str:
        d1, m1, d2, m2 = int(m.group(1)), m.group(2), int(m.group(3)), MESES[m.group(4)]
        rango(d1, MESES[m1] if m1 else m2, d2, m2)
        return " "
    t = pat.sub(sub_rango, t)
    # "los días 1, 8, 15, 22 y 29 de agosto", "7 y 31 de diciembre", "4 de abril"
    pat_lista = re.compile(rf"((?:\d{{1,2}}\s*(?:,|y)\s*)*\d{{1,2}})(?:\s+de)?\s+({mes})")
    def sub_lista(m: re.Match) -> str:
        mm = MESES[m.group(2)]
        for d in re.findall(r"\d{1,2}", m.group(1)):
            fechas.append(date(year, mm, int(d)))
        return " "
    t = pat_lista.sub(sub_lista, t)
    return sorted(set(fechas)), t


def vacations(anexo_i: list[str]) -> tuple[dict[int, dict[str, list[date]]], list[str]]:
    """Vacaciones por agrupación: {agr: {"MU:463": [fechas]}} y avisos de texto no interpretado."""
    out: dict[int, dict[str, list[date]]] = {}
    avisos: list[str] = []
    cur = None
    in_vac = False
    items: list[str] = []

    def flush() -> None:
        for item in items:
            m = _CODE_RE.search(item)
            if not m or cur is None:
                continue
            pid = f"MU:{int(m.group(1))}"
            resto_item = item[m.end():]
            try:
                fechas, resto = _parse_dates(resto_item)
            except ValueError as exc:
                avisos.append(f"Agrupación {cur}: {item} ({exc})")
                out.setdefault(cur, {})[pid] = []
                continue
            if re.search(r"\d", resto) or not fechas:
                avisos.append(f"Agrupación {cur}: vacaciones no interpretadas: {item}")
            out.setdefault(cur, {}).setdefault(pid, []).extend(fechas)
        items.clear()

    for line in anexo_i:
        m = _AGR_RE.match(line)
        if m:
            flush()
            cur, in_vac = int(m.group(1)), False
            continue
        if _SECTION_RE.match(line):
            flush()
            in_vac = "acacion" in line
            continue
        if not in_vac or not line.strip():
            continue
        s = line.strip()
        if s.startswith("-"):
            items.append(s.lstrip("- "))
        elif items:
            items[-1] += " " + s
    flush()
    return out, avisos


def _agr_number(zone: str) -> int | None:
    m = re.match(r"AGRUPACION\s+(\d+)", zone)
    return int(m.group(1)) if m else None


def evaluate_zone(
    zone: str,
    shifts: list[dict],
    zone_pharmacies: set[str],
    reglas: dict[int, str],
    vacaciones: dict[int, dict[str, list[date]]],
    cutoff: date = date(2026, 3, 1),
) -> Evaluacion | None:
    """Evalúa si la rotación de una zona con solo enero publicado puede proyectarse."""
    days: dict[date, list[str]] = {}
    for s in shifts:
        d = datetime.fromisoformat(s["start"]).astimezone(TZ).date()
        days.setdefault(d, []).append(s["pharmacy_id"])
    ordered = sorted(days)
    if not ordered or ordered[-1] >= cutoff:
        return None  # zona con cuadrante anual: nada que proyectar
    agr = _agr_number(zone)
    regla = reglas.get(agr, "") if agr is not None else ""
    seq = [tuple(sorted(days[d])) for d in ordered]
    n = len(seq)
    distinct = {p for t in seq for p in t}
    ev = Evaluacion(zone, agr, regla, n, len(distinct), None, None, None)
    ev.vacaciones = {p: v for p, v in vacaciones.get(agr, {}).items() if p in distinct}

    def fail(motivo: str) -> Evaluacion:
        ev.motivo = motivo
        return ev

    if ordered[0].year != 2026:
        return fail(f"el cuadrante publicado está fechado en {ordered[0].year} (errata del boletín)")
    if (ordered[-1] - ordered[0]).days + 1 != n:
        return fail("el cuadrante de enero tiene días sin turno")
    if any(len(t) != 1 for t in seq):
        return fail("hay días con más de una farmacia de turno")
    if not re.search(r"rotaci[oó]n", regla, re.IGNORECASE):
        return fail("el Anexo III no publica una regla de rotación")
    if "2025" in re.sub(r"31/12/2026", "", regla) and "31/12/2025" in regla:
        return fail("la regla dice 'hasta 31/12/2025' (errata del boletín)")
    low = regla.lower()
    # Yecla: "excepto los cambios señalados en el apartado anterior" = fechas publicadas aparte
    # (zona "Cambios de verano"), que project_zone respeta.
    low = low.replace("excepto los cambios señalados en el apartado anterior", "")
    bloqueos = [c for c in CONDICIONES_BLOQUEANTES if c in low]
    if bloqueos:
        return fail("la regla tiene condiciones que un ciclo simple no reproduce: " + ", ".join(bloqueos))
    if distinct != zone_pharmacies:
        return fail("no todas las farmacias de la zona aparecen en enero")

    periodo = next((p for p in range(1, n) if all(seq[i] == seq[i + p] for i in range(n - p))), None)
    if periodo is None:
        return fail("el cuadrante de enero no es periódico")
    ev.periodo = periodo
    semanal = "semana" in low
    if semanal:
        # Bloques de 7 días: cada farmacia ocupa días consecutivos y el ciclo es 7 x farmacias.
        if periodo != 7 * len(distinct):
            return fail(f"rotación semanal con periodo {periodo} días para {len(distinct)} farmacias")
        cambios = [i for i in range(1, n) if seq[i] != seq[i - 1]]
        if any((b - a) != 7 for a, b in zip(cambios, cambios[1:])):
            return fail("los bloques semanales de enero no son de 7 días")
        ev.tipo = "semanal"
    else:
        if "por días" not in low and "por dias" not in low:
            return fail("la regla no dice si la rotación es por días o por semanas")
        if periodo != len(distinct):
            return fail(f"ciclo diario de {periodo} días para {len(distinct)} farmacias")
        if n - periodo < periodo:
            return fail("enero no muestra el ciclo diario completo dos veces")
        ev.tipo = "diaria"
    return ev


def project_zone(
    ev: Evaluacion,
    shifts: list[dict],
    explicit_dates: set[date],
    until: date = YEAR_END,
) -> list[dict]:
    """Turnos proyectados para una zona proyectable (día siguiente al último publicado → until)."""
    assert ev.proyectable and ev.periodo
    by_day: dict[date, list[dict]] = {}
    for s in shifts:
        d = datetime.fromisoformat(s["start"]).astimezone(TZ).date()
        by_day.setdefault(d, []).append(s)
    first, last = min(by_day), max(by_day)
    out: list[dict] = []
    d = last + timedelta(days=1)
    vac = {p: set(v) for p, v in ev.vacaciones.items()}
    while d <= until:
        if d not in explicit_dates:
            plantilla = first + timedelta(days=(d - first).days % ev.periodo)
            for s in by_day[plantilla]:
                if d in vac.get(s["pharmacy_id"], set()):
                    continue  # de vacaciones: el BORM no dice quién sustituye
                delta = (d - plantilla).days
                start = datetime.fromisoformat(s["start"]).astimezone(TZ)
                end = datetime.fromisoformat(s["end"]).astimezone(TZ)
                # Mismo horario de reloj en el día de destino (zoneinfo resuelve el cambio de hora).
                ns = datetime.combine(start.date() + timedelta(days=delta), start.time(), TZ)
                ne = datetime.combine(end.date() + timedelta(days=delta), end.time(), TZ)
                out.append({
                    "pharmacy_id": s["pharmacy_id"],
                    "zone": s["zone"],
                    "start": ns.isoformat(),
                    "end": ne.isoformat(),
                    "kind": s["kind"],
                    "raw_label": f"{s['zone']} — DEDUCIDO de la regla de rotación del Anexo III (no publicado día a día)",
                    "times_exact": False,
                })
        d += timedelta(days=1)
    return out

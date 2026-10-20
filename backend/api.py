"""API REST con FastAPI para consulta de farmacias de guardia."""
from __future__ import annotations

import datetime
import json
import math
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.ambito import MUNICIPAL_SOURCES, SOURCE_AREAS, Box, inside_municipal_area, is_municipal
from backend.db import get_db
from backend.models import Pharmacy, Shift, Source

MADRID_TZ = ZoneInfo("Europe/Madrid")
EARTH_RADIUS_KM = 6371.0

app = FastAPI(
    title="Farmacias de Guardia API",
    description="API oficial de turnos de guardia para farmacias en España.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula la distancia ortodrómica en kilómetros entre dos coordenadas WGS84."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_KM * c


def to_madrid_iso(dt: datetime.datetime) -> str:
    """Convierte datetime UTC a formato ISO 8601 con zona horaria Europe/Madrid."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(MADRID_TZ).isoformat()


def select_best_shift_for_pharmacy(
    pharmacy: Pharmacy, shift_tuples: list[tuple[Shift, Source]]
) -> tuple[Shift, Source]:
    """Si una farmacia tiene varios turnos simultáneos (p.ej.

    citada en varios cuadrantes comarcales como guardia de referencia),
    selecciona el turno más específico para la localidad de la farmacia.
    """
    loc = (pharmacy.locality or "").strip().upper()

    def score(item: tuple[Shift, Source]) -> tuple[int, int]:
        s = item[0]
        z = (s.zone or "").strip().upper()
        raw = (s.raw_label or "").strip().upper()
        if loc and z == loc:
            match_score = 0
        elif loc and loc in z:
            match_score = 1
        elif loc and loc in raw:
            match_score = 2
        else:
            match_score = 3
        return (match_score, len(s.zone))

    return min(shift_tuples, key=score)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Estado del servicio y conteo de farmacias y turnos."""
    pharmacies_count = db.scalar(select(func.count()).select_from(Pharmacy)) or 0
    shifts_count = db.scalar(select(func.count()).select_from(Shift)) or 0
    return {
        "status": "ok",
        "pharmacies": pharmacies_count,
        "shifts": shifts_count,
    }


@app.get("/v1/fuentes")
def list_fuentes(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Lista de fuentes oficiales con su atribución y licencia."""
    sources = db.scalars(select(Source).order_by(Source.source_id)).all()
    now = datetime.datetime.now(datetime.timezone.utc)
    last_start = dict(db.execute(select(Shift.source_id, func.max(Shift.start_utc)).group_by(Shift.source_id)).all())
    zones = dict(
        db.execute(select(Shift.source_id, func.count(func.distinct(Shift.zone))).group_by(Shift.source_id)).all()
    )
    # Zonas con algún turno a menos de ZONE_GAP de hoy (Murcia: casi todas solo publican enero).
    current = dict(
        db.execute(
            select(Shift.source_id, func.count(func.distinct(Shift.zone)))
            .where(Shift.start_utc >= now - ZONE_GAP, Shift.start_utc < now + ZONE_GAP)
            .group_by(Shift.source_id)
        ).all()
    )
    return [
        {
            "source_id": s.source_id,
            "publisher": s.publisher,
            "url": s.url,
            "license": s.license,
            "retrieved_at": to_madrid_iso(s.retrieved_at),
            "municipal": is_municipal(s.source_id),
            "ambito": SOURCE_AREAS.get(s.source_id, s.publisher),
            "datos_hasta": to_madrid_iso(_as_utc(last_start[s.source_id])) if last_start.get(s.source_id) else None,
            "zonas": zones.get(s.source_id, 0),
            "zonas_con_turnos": current.get(s.source_id, 0),
        }
        for s in sources
    ]


@app.get("/v1/farmacias/{pharmacy_id}")
def get_farmacia(pharmacy_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Ficha completa de farmacia y sus próximos 3 turnos."""
    pharmacy = db.get(Pharmacy, pharmacy_id)
    if pharmacy is None:
        raise HTTPException(status_code=404, detail="Farmacia no encontrada")

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    shifts = db.scalars(
        select(Shift)
        .where(Shift.pharmacy_id == pharmacy_id, Shift.end_utc >= now_utc)
        .order_by(Shift.start_utc.asc())
        .limit(3)
    ).all()

    source = pharmacy.source
    return {
        "id": pharmacy.id,
        "region": pharmacy.region,
        "titular": pharmacy.holder,
        "direccion": pharmacy.address,
        "localidad": pharmacy.locality,
        "cp": pharmacy.postal_code,
        "telefono": pharmacy.phone,
        "telefono_guardia": pharmacy.duty_phone,
        "lat": pharmacy.lat,
        "lon": pharmacy.lon,
        "geo_precision": pharmacy.geo_precision,
        "ubicacion_aproximada": bool(pharmacy.geo_precision == "localidad"),
        "fuente": {
            "source_id": source.source_id if source else None,
            "publisher": source.publisher if source else None,
            "url": source.url if source else None,
            "license": source.license if source else None,
        },
        "proximos_turnos": [
            {
                "tipo": s.kind,
                "inicio": to_madrid_iso(s.start_utc),
                "fin": to_madrid_iso(s.end_utc),
                "zona": s.zone,
                "etiqueta_original": s.raw_label,
                "horario_confirmado": bool(s.times_exact),
            }
            for s in shifts
        ],
    }



MSG_SIN_ZONA = "Sin datos oficiales para esta zona"
MSG_SIN_FECHA = "Sin datos oficiales para esta fecha"
MSG_SIN_PUBLICAR = "Aún no hay turnos oficiales publicados para esta fecha"
MSG_ANTERIOR = "No tenemos los turnos oficiales de esa fecha"
MSG_ZONA_SIN_PUBLICAR = "Sin turnos oficiales publicados para tu zona en esta fecha"
# Una zona con turnos a menos de esta distancia de la fecha se considera publicada (cuadrantes
# semanales o de fin de semana sin turno todos los días).
ZONE_GAP = datetime.timedelta(days=7)


def _parse_at(at: str | None) -> datetime.datetime:
    if at is None:
        return datetime.datetime.now(datetime.timezone.utc)
    try:
        dt = datetime.datetime.fromisoformat(at)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Formato de 'at' inválido. Use ISO 8601 (ej. 2026-10-18T23:00:00+02:00)",
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MADRID_TZ)
    return dt.astimezone(datetime.timezone.utc)


def _municipal_boxes(db: Session) -> dict[str, Box]:
    """Caja de las farmacias de cada fuente municipal (solo respaldo si falta el polígono)."""
    rows = db.execute(
        select(
            Pharmacy.source_id,
            func.min(Pharmacy.lat),
            func.min(Pharmacy.lon),
            func.max(Pharmacy.lat),
            func.max(Pharmacy.lon),
        )
        .where(
            Pharmacy.source_id.in_(list(MUNICIPAL_SOURCES)),
            Pharmacy.lat.is_not(None),
            Pharmacy.lon.is_not(None),
        )
        .group_by(Pharmacy.source_id)
    ).all()
    return {sid: (a, b, c, d) for sid, a, b, c, d in rows}


def _nearby_pharmacies(
    db: Session, lat: float, lon: float, radius_km: float
) -> dict[str, tuple[Pharmacy, float]]:
    """Farmacias con coordenadas a menos de radius_km, respetando el ámbito de las fuentes municipales."""
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.01, math.cos(math.radians(lat))))
    candidates = db.scalars(
        select(Pharmacy).where(
            Pharmacy.lat.is_not(None),
            Pharmacy.lon.is_not(None),
            Pharmacy.lat.between(lat - dlat, lat + dlat),
            Pharmacy.lon.between(lon - dlon, lon + dlon),
        )
    ).all()
    boxes: dict[str, Box] | None = None
    out: dict[str, tuple[Pharmacy, float]] = {}
    for p in candidates:
        if is_municipal(p.source_id):
            if boxes is None:
                boxes = _municipal_boxes(db)
            # Alcalá no es Madrid: una fuente municipal no vale fuera de su término.
            if not inside_municipal_area(p.source_id, lat, lon, boxes.get(p.source_id)):
                continue
        dist = haversine_km(lat, lon, p.lat, p.lon)  # type: ignore[arg-type]
        if dist <= radius_km:
            out[p.id] = (p, dist)
    return out


def _published_period(
    db: Session, source_ids: set[str]
) -> dict[str, tuple[datetime.datetime, datetime.datetime]]:
    """(primer inicio, último fin, último inicio) de los turnos publicados por cada fuente."""
    if not source_ids:
        return {}
    rows = db.execute(
        select(Shift.source_id, func.min(Shift.start_utc), func.max(Shift.end_utc), func.max(Shift.start_utc))
        .where(Shift.source_id.in_(list(source_ids)))
        .group_by(Shift.source_id)
    ).all()
    out = {}
    for sid, first, last, last_start in rows:
        # func.min/max devuelven el valor crudo de SQLite (naive o texto): normalizar a UTC.
        out[sid] = (_as_utc(first), _as_utc(last), _as_utc(last_start))
    return out


def _as_utc(value: Any) -> datetime.datetime:
    if isinstance(value, str):
        value = datetime.datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def _pharmacy_zones(pharmacy: Pharmacy) -> set[str]:
    if not pharmacy.zones:
        return set()
    try:
        zs = json.loads(pharmacy.zones)
    except (TypeError, ValueError):
        return set()
    return set(zs) if isinstance(zs, list) else set()


def _count_unlocated(
    db: Session, nearby: dict[str, tuple[Pharmacy, float]], start: datetime.datetime, end: datetime.datetime
) -> int:
    """Farmacias de guardia en [start, end) sin coordenadas cuyas zonas coinciden con las cercanas."""
    nearby_zones: set[str] = set()
    for p, _ in nearby.values():
        nearby_zones |= _pharmacy_zones(p)
    if not nearby_zones:
        return 0
    if start == end:
        overlap = (Shift.start_utc <= start, Shift.end_utc > start)
    else:
        overlap = (Shift.start_utc < end, Shift.end_utc > start)
    unlocated = db.scalars(
        select(Pharmacy)
        .join(Shift, Shift.pharmacy_id == Pharmacy.id)
        .where((Pharmacy.lat.is_(None) | Pharmacy.lon.is_(None)), *overlap)
        .distinct()
    ).all()
    return sum(1 for up in unlocated if _pharmacy_zones(up) & nearby_zones)


def _zone_notice(
    db: Session,
    nearby: dict[str, tuple[Pharmacy, float]],
    start: datetime.datetime,
    end: datetime.datetime,
    instant: bool,
) -> str | None:
    """Aviso si la zona de la farmacia más cercana no tiene turnos publicados para la fecha.

    Caso típico: agrupaciones de Murcia con solo el cuadrante de enero publicado; sin el aviso,
    la app mostraría guardias de otra agrupación como si fueran las de la zona.
    """
    with_shifts = set(
        db.scalars(select(Shift.pharmacy_id).where(Shift.pharmacy_id.in_(list(nearby))).distinct()).all()
    )
    if not with_shifts:
        return None
    nearest = min(with_shifts, key=lambda pid: nearby[pid][1])
    zones = select(Shift.zone).where(Shift.pharmacy_id == nearest).distinct()
    rows = db.execute(
        select(Shift.zone, func.min(Shift.start_utc), func.max(Shift.start_utc), func.max(Shift.end_utc))
        .where(Shift.zone.in_(zones))
        .group_by(Shift.zone)
    ).all()
    if not rows:
        return None
    probe = start if instant else end - datetime.timedelta(microseconds=1)
    # Publicada = dentro del periodo de la zona y con algún turno a menos de ZONE_GAP (Yecla publica
    # enero y agosto: marzo no está publicado aunque caiga entre los dos).
    near = db.scalar(
        select(Shift.id)
        .where(Shift.zone.in_(zones), Shift.start_utc < end + ZONE_GAP, Shift.start_utc >= start - ZONE_GAP)
        .limit(1)
    )
    if near is not None and any(_as_utc(first) <= probe and start < _as_utc(last) for _, first, _, last in rows):
        return None
    zonas = ", ".join(sorted(r[0] for r in rows))
    last_start = max(_as_utc(r[2]) for r in rows).astimezone(MADRID_TZ)
    if start >= max(_as_utc(r[3]) for r in rows):
        return (
            f"La fuente oficial solo ha publicado los turnos de tu zona ({zonas}) "
            f"hasta el {last_start.day}/{last_start.month}/{last_start.year}."
        )
    return f"La fuente oficial no ha publicado los turnos de tu zona ({zonas}) para esta fecha."


def _item(pharmacy: Pharmacy, shift: Shift, source: Source, dist: float) -> dict[str, Any]:
    return {
        "farmacia": {
            "id": pharmacy.id,
            "titular": pharmacy.holder,
            "direccion": pharmacy.address,
            "localidad": pharmacy.locality,
            "cp": pharmacy.postal_code,
            "telefono": pharmacy.phone,
            "telefono_guardia": pharmacy.duty_phone,
            "lat": pharmacy.lat,
            "lon": pharmacy.lon,
            "geo_precision": pharmacy.geo_precision,
            "ubicacion_aproximada": bool(pharmacy.geo_precision == "localidad"),
        },
        "turno": {
            "tipo": shift.kind,
            "inicio": to_madrid_iso(shift.start_utc),
            "fin": to_madrid_iso(shift.end_utc),
            "zona": shift.zone,
            "etiqueta_original": shift.raw_label,
            "horario_confirmado": bool(shift.times_exact),
        },
        "distancia_km": round(dist, 2),
        "fuente": {
            "publisher": source.publisher,
            "url": source.url,
            "license": source.license,
        },
    }


def _query_guardias(
    db: Session,
    lat: float,
    lon: float,
    start: datetime.datetime,
    end: datetime.datetime,
    radius_km: float,
    limit: int,
) -> dict[str, Any]:
    """Guardias que se solapan con [start, end). Si start == end, las activas en ese instante.

    Reglas compartidas con la app (GuardiasEngine):
    - "Sin datos oficiales para esta zona": ninguna farmacia con turnos en el radio.
    - "Aún no hay turnos oficiales publicados para esta fecha": la fecha cae fuera del periodo
      publicado por las fuentes de la zona (no es que no haya guardia: es que aún no la conocemos).
    - "Sin datos oficiales para esta fecha": la fecha está publicada pero no hay turno asignado.
    """
    instant = start == end
    nearby = _nearby_pharmacies(db, lat, lon, radius_km)
    has_any_shift = bool(nearby) and (
        db.scalar(select(Shift.id).where(Shift.pharmacy_id.in_(list(nearby))).limit(1)) is not None
    )
    if not has_any_shift:
        return {
            "cobertura": False,
            "mensaje": MSG_SIN_ZONA,
            "aviso": None,
            "farmacias_sin_coordenadas": 0,
            "datos_hasta": None,
            "guardias": [],
        }

    periods = _published_period(db, {p.source_id for p, _ in nearby.values()})
    # "Publicados hasta": inicio del último turno (una nocturna del 31/12 acaba el 1/1).
    published_until = max((p[2] for p in periods.values()), default=None)
    probe = start if instant else end - datetime.timedelta(microseconds=1)
    covered = any(first <= probe and start < last for first, last, _ in periods.values())
    # Antes del primer turno que tenemos: no es "aún no publicado", es que no lo tenemos.
    before_data = bool(periods) and all(probe < first for first, _, _ in periods.values())

    unlocated = _count_unlocated(db, nearby, start, end)
    aviso = _zone_notice(db, nearby, start, end, instant) if covered else None

    if instant:
        # Urgencia diurna sin horario publicado (Murcia): solo en la vista de día, no "ahora".
        overlap = (
            Shift.start_utc <= start,
            Shift.end_utc > start,
            ~((Shift.kind == "diurna") & (Shift.times_exact.is_(False))),
        )
    else:
        overlap = (Shift.start_utc < end, Shift.end_utc > start)
    rows = db.execute(
        select(Shift, Source)
        .join(Source, Shift.source_id == Source.source_id)
        .where(Shift.pharmacy_id.in_(list(nearby)), *overlap)
    ).all()

    # Una farmacia citada en varios cuadrantes a la misma hora se muestra una vez: en el modo
    # instante se agrupa por farmacia; en el modo día, por (farmacia, tipo, inicio).
    groups: dict[tuple, list[tuple[Shift, Source]]] = {}
    for shift, source in rows:
        key = (shift.pharmacy_id,) if instant else (shift.pharmacy_id, shift.kind, shift.start_utc)
        groups.setdefault(key, []).append((shift, source))

    items = []
    for key, shift_tuples in groups.items():
        pharmacy, dist = nearby[key[0]]
        best_shift, source = select_best_shift_for_pharmacy(pharmacy, shift_tuples)
        items.append(_item(pharmacy, best_shift, source, dist))

    if instant:
        items.sort(key=lambda x: (x["distancia_km"], x["turno"]["inicio"]))
    else:
        items.sort(key=lambda x: (x["turno"]["inicio"], x["distancia_km"]))

    mensaje = None
    if not items:
        if aviso:
            mensaje = MSG_ZONA_SIN_PUBLICAR
        elif covered:
            mensaje = MSG_SIN_FECHA
        else:
            mensaje = MSG_ANTERIOR if before_data else MSG_SIN_PUBLICAR
    if aviso:
        aviso += " Se muestran guardias de zonas cercanas." if items else " No hay guardias de zonas cercanas."
    return {
        "cobertura": True,
        "mensaje": mensaje,
        "aviso": aviso,
        "farmacias_sin_coordenadas": unlocated,
        "datos_hasta": to_madrid_iso(published_until) if published_until else None,
        "guardias": items[:limit],
    }


@app.get("/v1/guardias")
def get_guardias(
    lat: float = Query(..., description="Latitud de consulta (WGS84)"),
    lon: float = Query(..., description="Longitud de consulta (WGS84)"),
    at: str | None = Query(None, description="Instante ISO 8601 (por defecto ahora)"),
    radius_km: float = Query(25.0, description="Radio de búsqueda en km"),
    limit: int = Query(20, description="Límite máximo de resultados"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Farmacias de guardia en el instante 'at' ordenadas por distancia."""
    at_utc = _parse_at(at)
    return _query_guardias(db, lat, lon, at_utc, at_utc, radius_km, limit)


@app.get("/v1/guardias/dia")
def get_guardias_dia(
    lat: float = Query(..., description="Latitud de consulta (WGS84)"),
    lon: float = Query(..., description="Longitud de consulta (WGS84)"),
    fecha: str = Query(..., description="Fecha en formato YYYY-MM-DD"),
    radius_km: float = Query(25.0, description="Radio de búsqueda en km"),
    limit: int = Query(500, description="Límite máximo de resultados"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Turnos de guardia que se solapan con el día natural en Europe/Madrid."""
    try:
        d = datetime.date.fromisoformat(fecha)
        if not datetime.date(2000, 1, 1) <= d <= datetime.date(2100, 12, 31):
            raise ValueError(fecha)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Formato de 'fecha' inválido. Use YYYY-MM-DD (ej. 2026-10-18)",
        )
    day_start = datetime.datetime(d.year, d.month, d.day, tzinfo=MADRID_TZ)
    # El día siguiente a medianoche en hora de Madrid (23 o 25 h en los cambios de hora).
    nxt = d + datetime.timedelta(days=1)
    day_end = datetime.datetime(nxt.year, nxt.month, nxt.day, tzinfo=MADRID_TZ)
    return _query_guardias(
        db,
        lat,
        lon,
        day_start.astimezone(datetime.timezone.utc),
        day_end.astimezone(datetime.timezone.utc),
        radius_km,
        limit,
    )

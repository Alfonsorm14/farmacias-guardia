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
    return [
        {
            "source_id": s.source_id,
            "publisher": s.publisher,
            "url": s.url,
            "license": s.license,
            "retrieved_at": to_madrid_iso(s.retrieved_at),
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
    if at is None:
        at_utc = datetime.datetime.now(datetime.timezone.utc)
    else:
        try:
            dt = datetime.datetime.fromisoformat(at)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Formato de 'at' inválido. Use ISO 8601 (ej. 2026-10-18T23:00:00+02:00)",
            )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=MADRID_TZ)
        at_utc = dt.astimezone(datetime.timezone.utc)

    # 1. Prefiltro SQL por bounding box
    dlat = radius_km / 111.0
    cos_lat = max(0.01, math.cos(math.radians(lat)))
    dlon = radius_km / (111.0 * cos_lat)
    lat_min, lat_max = lat - dlat, lat + dlat
    lon_min, lon_max = lon - dlon, lon + dlon

    candidate_pharmacies = db.scalars(
        select(Pharmacy).where(
            Pharmacy.lat.is_not(None),
            Pharmacy.lon.is_not(None),
            Pharmacy.lat.between(lat_min, lat_max),
            Pharmacy.lon.between(lon_min, lon_max),
        )
    ).all()

    nearby_pharmacies: dict[str, tuple[Pharmacy, float]] = {}
    for p in candidate_pharmacies:
        dist = haversine_km(lat, lon, p.lat, p.lon)  # type: ignore[arg-type]
        if dist <= radius_km:
            nearby_pharmacies[p.id] = (p, dist)

    # 2. Comprobar cobertura (si existe ALGÚN turno de cualquier fecha a menos de radius_km)
    if not nearby_pharmacies:
        has_any_shift = False
    else:
        has_any_shift = (
            db.scalar(
                select(Shift.id)
                .where(Shift.pharmacy_id.in_(list(nearby_pharmacies.keys())))
                .limit(1)
            )
            is not None
        )

    if not has_any_shift:
        return {
            "cobertura": False,
            "mensaje": "Sin datos oficiales para esta zona",
            "farmacias_sin_coordenadas": 0,
            "guardias": [],
        }

    # 3. Contar farmacias activas en 'at' sin coordenadas cuyas zones coincidan con las cercanas
    nearby_zones: set[str] = set()
    for p, _ in nearby_pharmacies.values():
        if p.zones:
            try:
                zs = json.loads(p.zones)
                if isinstance(zs, list):
                    nearby_zones.update(zs)
            except Exception:
                pass

    farmacias_sin_coordenadas = 0
    if nearby_zones:
        unlocated_pharmacies = db.scalars(
            select(Pharmacy)
            .join(Shift, Shift.pharmacy_id == Pharmacy.id)
            .where(
                (Pharmacy.lat.is_(None) | Pharmacy.lon.is_(None)),
                Shift.start_utc <= at_utc,
                Shift.end_utc > at_utc,
            )
            .distinct()
        ).all()
        for up in unlocated_pharmacies:
            if up.zones:
                try:
                    up_zs = set(json.loads(up.zones))
                    if up_zs & nearby_zones:
                        farmacias_sin_coordenadas += 1
                except Exception:
                    pass

    # 4. Turnos activos en 'at' para farmacias cercanas
    shifts_stmt = (
        select(Shift, Source)
        .join(Source, Shift.source_id == Source.source_id)
        .where(
            Shift.pharmacy_id.in_(list(nearby_pharmacies.keys())),
            Shift.start_utc <= at_utc,
            Shift.end_utc > at_utc,
        )
    )
    active_shifts = db.execute(shifts_stmt).all()

    if not active_shifts:
        return {
            "cobertura": True,
            "mensaje": "Sin datos oficiales para esta fecha",
            "farmacias_sin_coordenadas": farmacias_sin_coordenadas,
            "guardias": [],
        }

    # Agrupar por farmacia para no duplicar una misma farmacia activa en varios cuadrantes
    shifts_by_pharmacy: dict[str, list[tuple[Shift, Source]]] = {}
    for shift, source in active_shifts:
        shifts_by_pharmacy.setdefault(shift.pharmacy_id, []).append((shift, source))

    items = []
    for pid, shift_tuples in shifts_by_pharmacy.items():
        pharmacy, dist = nearby_pharmacies[pid]
        best_shift, source = select_best_shift_for_pharmacy(
            pharmacy, shift_tuples
        )
        items.append(
            {
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
                    "tipo": best_shift.kind,
                    "inicio": to_madrid_iso(best_shift.start_utc),
                    "fin": to_madrid_iso(best_shift.end_utc),
                    "zona": best_shift.zone,
                    "etiqueta_original": best_shift.raw_label,
                    "horario_confirmado": bool(best_shift.times_exact),
                },
                "distancia_km": round(dist, 2),
                "fuente": {
                    "publisher": source.publisher,
                    "url": source.url,
                    "license": source.license,
                },
            }
        )

    # Ordenar por distancia
    items.sort(key=lambda x: (x["distancia_km"], x["turno"]["inicio"]))
    items = items[:limit]

    return {
        "cobertura": True,
        "mensaje": None,
        "farmacias_sin_coordenadas": farmacias_sin_coordenadas,
        "guardias": items,
    }


@app.get("/v1/guardias/dia")
def get_guardias_dia(
    lat: float = Query(..., description="Latitud de consulta (WGS84)"),
    lon: float = Query(..., description="Longitud de consulta (WGS84)"),
    fecha: str = Query(..., description="Fecha en formato YYYY-MM-DD"),
    radius_km: float = Query(25.0, description="Radio de búsqueda en km"),
    limit: int = Query(50, description="Límite máximo de resultados"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Turnos de guardia que se solapan con el día natural en Europe/Madrid."""
    try:
        d = datetime.date.fromisoformat(fecha)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Formato de 'fecha' inválido. Use YYYY-MM-DD (ej. 2026-10-18)",
        )

    day_start_local = datetime.datetime(
        d.year, d.month, d.day, 0, 0, 0, tzinfo=MADRID_TZ
    )
    day_end_local = day_start_local + datetime.timedelta(days=1)
    day_start_utc = day_start_local.astimezone(datetime.timezone.utc)
    day_end_utc = day_end_local.astimezone(datetime.timezone.utc)

    # 1. Prefiltro SQL por bounding box
    dlat = radius_km / 111.0
    cos_lat = max(0.01, math.cos(math.radians(lat)))
    dlon = radius_km / (111.0 * cos_lat)
    lat_min, lat_max = lat - dlat, lat + dlat
    lon_min, lon_max = lon - dlon, lon + dlon

    candidate_pharmacies = db.scalars(
        select(Pharmacy).where(
            Pharmacy.lat.is_not(None),
            Pharmacy.lon.is_not(None),
            Pharmacy.lat.between(lat_min, lat_max),
            Pharmacy.lon.between(lon_min, lon_max),
        )
    ).all()

    nearby_pharmacies: dict[str, tuple[Pharmacy, float]] = {}
    for p in candidate_pharmacies:
        dist = haversine_km(lat, lon, p.lat, p.lon)  # type: ignore[arg-type]
        if dist <= radius_km:
            nearby_pharmacies[p.id] = (p, dist)

    # 2. Comprobar cobertura
    if not nearby_pharmacies:
        has_any_shift = False
    else:
        has_any_shift = (
            db.scalar(
                select(Shift.id)
                .where(Shift.pharmacy_id.in_(list(nearby_pharmacies.keys())))
                .limit(1)
            )
            is not None
        )

    if not has_any_shift:
        return {
            "cobertura": False,
            "mensaje": "Sin datos oficiales para esta zona",
            "farmacias_sin_coordenadas": 0,
            "guardias": [],
        }

    # 3. Contar farmacias sin coordenadas con turnos que solapan el día cuyas zones coincidan con las cercanas
    nearby_zones: set[str] = set()
    for p, _ in nearby_pharmacies.values():
        if p.zones:
            try:
                zs = json.loads(p.zones)
                if isinstance(zs, list):
                    nearby_zones.update(zs)
            except Exception:
                pass

    farmacias_sin_coordenadas = 0
    if nearby_zones:
        unlocated_pharmacies = db.scalars(
            select(Pharmacy)
            .join(Shift, Shift.pharmacy_id == Pharmacy.id)
            .where(
                (Pharmacy.lat.is_(None) | Pharmacy.lon.is_(None)),
                Shift.start_utc < day_end_utc,
                Shift.end_utc > day_start_utc,
            )
            .distinct()
        ).all()
        for up in unlocated_pharmacies:
            if up.zones:
                try:
                    up_zs = set(json.loads(up.zones))
                    if up_zs & nearby_zones:
                        farmacias_sin_coordenadas += 1
                except Exception:
                    pass

    # 4. Turnos solapados para farmacias cercanas
    shifts_stmt = (
        select(Shift, Source)
        .join(Source, Shift.source_id == Source.source_id)
        .where(
            Shift.pharmacy_id.in_(list(nearby_pharmacies.keys())),
            Shift.start_utc < day_end_utc,
            Shift.end_utc > day_start_utc,
        )
    )
    day_shifts = db.execute(shifts_stmt).all()

    if not day_shifts:
        return {
            "cobertura": True,
            "mensaje": "Sin datos oficiales para esta fecha",
            "farmacias_sin_coordenadas": farmacias_sin_coordenadas,
            "guardias": [],
        }

    # Agrupar por (pharmacy_id, kind, start_utc) para evitar duplicados del mismo turno en varias zonas
    day_shifts_by_key: dict[
        tuple[str, str, datetime.datetime], list[tuple[Shift, Source]]
    ] = {}
    for shift, source in day_shifts:
        key = (shift.pharmacy_id, shift.kind, shift.start_utc)
        day_shifts_by_key.setdefault(key, []).append((shift, source))

    items = []
    for (pid, kind, _), shift_tuples in day_shifts_by_key.items():
        pharmacy, dist = nearby_pharmacies[pid]
        best_shift, source = select_best_shift_for_pharmacy(
            pharmacy, shift_tuples
        )
        items.append(
            {
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
                    "tipo": best_shift.kind,
                    "inicio": to_madrid_iso(best_shift.start_utc),
                    "fin": to_madrid_iso(best_shift.end_utc),
                    "zona": best_shift.zone,
                    "etiqueta_original": best_shift.raw_label,
                    "horario_confirmado": bool(best_shift.times_exact),
                },
                "distancia_km": round(dist, 2),
                "fuente": {
                    "publisher": source.publisher,
                    "url": source.url,
                    "license": source.license,
                },
            }
        )

    # Ordenar por inicio y distancia
    items.sort(key=lambda x: (x["turno"]["inicio"], x["distancia_km"]))
    items = items[:limit]

    return {
        "cobertura": True,
        "mensaje": None,
        "farmacias_sin_coordenadas": farmacias_sin_coordenadas,
        "guardias": items,
    }

"""Ámbito territorial de las fuentes.

Las fuentes municipales (un ayuntamiento que publica las guardias de su término) no valen fuera
de él: las farmacias de Madrid capital no son la guardia de Alcalá, Getafe, Pozuelo o Coslada
aunque estén a menos de 25 km. La API y la app (export_snapshot -> GuardiasEngine) aplican la misma
regla: una farmacia de fuente municipal solo se ofrece si el punto consultado está dentro del
término municipal (polígono de data/geo/municipios.json, límites de OpenStreetMap).

El polígono es fijo: no depende de qué farmacias estén de guardia ese día (Zaragoza publica solo
las 7 del día en curso, y una caja derivada de ellas dejaba fuera barrios enteros).
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

# Fuentes que solo cubren un término municipal.
MUNICIPAL_SOURCES: frozenset[str] = frozenset({"MAD-AYTO-DATOSABIERTOS", "ZGZ-AYTO"})

MUNICIPIOS_PATH = Path(__file__).resolve().parent.parent / "data" / "geo" / "municipios.json"

# Margen de la caja de respaldo (solo si faltara el polígono de una fuente municipal).
MUNICIPAL_MARGIN_KM = 2.0

Box = tuple[float, float, float, float]  # lat_min, lon_min, lat_max, lon_max
Ring = list[tuple[float, float]]  # [(lat, lon), ...]


def is_municipal(source_id: str | None) -> bool:
    return source_id in MUNICIPAL_SOURCES


@lru_cache(maxsize=1)
def municipal_polygons() -> dict[str, list[list[Ring]]]:
    """{source_id: [polígono = [anillo exterior, huecos...]]} desde data/geo/municipios.json."""
    try:
        data = json.loads(MUNICIPIOS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        sid: [[[(p[0], p[1]) for p in ring] for ring in poly] for poly in m["poligonos"]]
        for sid, m in data.get("municipios", {}).items()
    }


def _in_ring(ring: Ring, lat: float, lon: float) -> bool:
    """Ray casting (par/impar) sobre un anillo [(lat, lon)]."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        yi, xi = ring[i]
        yj, xj = ring[j]
        if (yi > lat) != (yj > lat):
            x_cross = xi + (lat - yi) * (xj - xi) / (yj - yi)
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def inside_polygons(polygons: list[list[Ring]], lat: float, lon: float) -> bool:
    for poly in polygons:
        if poly and _in_ring(poly[0], lat, lon) and not any(_in_ring(h, lat, lon) for h in poly[1:]):
            return True
    return False


def inside_box(box: Box | None, lat: float, lon: float, margin_km: float = MUNICIPAL_MARGIN_KM) -> bool:
    """¿(lat, lon) cae en la caja ampliada en margin_km? Sin caja -> no."""
    if box is None:
        return False
    dlat = margin_km / 111.0
    dlon = margin_km / (111.0 * max(0.01, math.cos(math.radians(lat))))
    lat_min, lon_min, lat_max, lon_max = box
    return lat_min - dlat <= lat <= lat_max + dlat and lon_min - dlon <= lon <= lon_max + dlon


def inside_municipal_area(source_id: str, lat: float, lon: float, fallback_box: Box | None = None) -> bool:
    """¿El punto está en el término de la fuente municipal? Sin polígono, caja de respaldo."""
    polygons = municipal_polygons().get(source_id)
    if polygons:
        return inside_polygons(polygons, lat, lon)
    return inside_box(fallback_box, lat, lon)

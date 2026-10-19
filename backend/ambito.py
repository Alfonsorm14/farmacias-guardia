"""Ámbito territorial de las fuentes.

Las fuentes municipales (un ayuntamiento que publica las guardias de su término) no valen fuera
de él: las farmacias de Madrid capital no son la guardia de Alcalá de Henares aunque estén a menos
de 25 km. La API y la app (export_snapshot -> GuardiasEngine) aplican la misma regla: una farmacia
de fuente municipal solo se ofrece si el punto consultado cae dentro de la caja que envuelve a las
farmacias geolocalizadas de esa fuente, ampliada en MUNICIPAL_MARGIN_KM.
"""
from __future__ import annotations

import math

# Fuentes que solo cubren un término municipal.
MUNICIPAL_SOURCES: frozenset[str] = frozenset({"MAD-AYTO-DATOSABIERTOS", "ZGZ-AYTO"})

# Margen alrededor de la caja de farmacias de la fuente (mismo valor que la app).
MUNICIPAL_MARGIN_KM = 2.0

Box = tuple[float, float, float, float]  # lat_min, lon_min, lat_max, lon_max


def is_municipal(source_id: str | None) -> bool:
    return source_id in MUNICIPAL_SOURCES


def inside_box(box: Box | None, lat: float, lon: float, margin_km: float = MUNICIPAL_MARGIN_KM) -> bool:
    """¿(lat, lon) cae en la caja ampliada en margin_km? Sin caja (fuente sin coordenadas) -> no."""
    if box is None:
        return False
    dlat = margin_km / 111.0
    dlon = margin_km / (111.0 * max(0.01, math.cos(math.radians(lat))))
    lat_min, lon_min, lat_max, lon_max = box
    return lat_min - dlat <= lat <= lat_max + dlat and lon_min - dlon <= lon <= lon_max + dlon

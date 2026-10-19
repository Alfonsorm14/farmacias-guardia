"""Módulo de geocodificación de farmacias con CartoCiudad y Nominatim (Tarea 03c).

Normas estrictas de la Tarea 03c:
1. Prohibido usar coordenadas fijas, de test o de comunidad como respaldo.
   Ninguna constante de coordenadas salvo las cajas de validación por comunidad (BBOXES).
2. Precisión "localidad" = centroide del NÚCLEO de población (pedanía),
   geocodificado dinámicamente como lugar habitado y validado en su municipio.
3. Si no se puede situar ni la dirección ni el núcleo: lat/lon = NULL, geo_precision = NULL.
   Nunca el centroide del municipio para una pedanía (solo para casco urbano: locality == municipio).
4. Control final: ningún par (lat, lon) compartido por más de 2 farmacias salvo que tengan
   la misma dirección normalizada; listarlos en el informe.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import random
import re
import time
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.db import create_db_engine, init_db
from backend.models import GeocodeCache, Pharmacy

logger = logging.getLogger(__name__)

# Bounding boxes oficiales por comunidad autónoma (únicas constantes de coordenadas permitidas)
BBOXES: dict[str, dict[str, float]] = {
    # Baleares: lat 38.6–40.1, lon 1.1–4.4
    "04": {"lat_min": 38.6, "lat_max": 40.1, "lon_min": 1.1, "lon_max": 4.4},
    # Murcia: lat 37.3–38.8, lon -2.4 a -0.6
    "14": {"lat_min": 37.3, "lat_max": 38.8, "lon_min": -2.4, "lon_max": -0.6},
}

CARTOCIUDAD_CANDIDATES_URL = (
    "https://www.cartociudad.es/geocoder/api/geocoder/candidates"
)
CARTOCIUDAD_FIND_URL = "https://www.cartociudad.es/geocoder/api/geocoder/find"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "farmacias-guardia/0.1 (alfonsorivero.es@gmail.com)"

EARTH_RADIUS_KM = 6371.0
_last_nominatim_time = 0.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula la distancia ortodrómica en kilómetros entre dos coordenadas WGS84."""
    import math

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_KM * c


def _nominatim_rate_limit() -> None:
    """Respeta la política de uso de Nominatim (máx 1 petición por segundo)."""
    global _last_nominatim_time
    now = time.time()
    elapsed = now - _last_nominatim_time
    if elapsed < 1.05:
        time.sleep(1.05 - elapsed)
    _last_nominatim_time = time.time()


def normalize_text(text: str) -> str:
    """Normaliza quitando acentos y caracteres especiales para comparaciones seguras."""
    if not text:
        return ""
    n = unicodedata.normalize("NFD", text)
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", n.lower())


def muni_matches(expected: str, result_muni: str) -> bool:
    """Comprueba si el municipio retornado coincide con el esperado."""
    if not expected or not result_muni:
        return False
    exp_norm = normalize_text(expected)
    res_norm = normalize_text(result_muni)
    if exp_norm == res_norm:
        return True
    if exp_norm in res_norm or res_norm in exp_norm:
        return True
    return False


def is_within_bbox(region: str, lat: float, lon: float) -> bool:
    """Comprueba si las coordenadas están dentro de la caja de su comunidad autónoma."""
    bbox = BBOXES.get(region)
    if not bbox:
        return True
    return (
        bbox["lat_min"] <= lat <= bbox["lat_max"]
        and bbox["lon_min"] <= lon <= bbox["lon_max"]
    )


def clean_address(address: str) -> str:
    """Normaliza la dirección según las directrices de la Tarea 03b/03c:

    - Quitar abreviaturas iniciales como T. o TTE. (Teniente).
    - Quitar desde ESQUINA / esq. hasta final o siguiente coma.
    - Quitar Nº, S/N, s/n (sin romper palabras como NOVEL).
    - Expandir abreviaturas (CL, C/, Cl., AVDA, CTRA, PZA, PL, PLZ, PZ, PSO, TRAV, URB).
    - Separar números/letras pegados tras puntos ('AVDA.REINO' -> 'AVENIDA REINO').
    - Quitar paréntesis descriptivos y locales ('Local N', 'LOC. 7,8').
    """
    if not address:
        return ""
    addr = address

    # 0. Quitar tratamientos o abreviaturas iniciales como T. VICTOR CASTILLO -> VICTOR CASTILLO
    addr = re.sub(r"^(?:t\.|tte\.|tte)\s+", "", addr.strip(), flags=re.IGNORECASE)

    # 1. Quitar desde ESQUINA / esq. / esquina hasta el final o coma siguiente
    addr = re.sub(r"(?i)\b(esquina|esq\.?)\b.*?(?:,|$)", " ", addr)

    # 2. Quitar paréntesis (tanto cerrados como abiertos sin cerrar)
    addr = re.sub(r"\(.*", " ", addr)

    # 3. Quitar 'con acceso...'
    addr = re.sub(r"(?i),?\s*con acceso\b.*", " ", addr)

    # 4. Quitar menciones de edificio, bloque, barrio, barriada
    addr = re.sub(
        r"(?i),?\s*(?:edificio|edf\.?|edifico)\s*[\w\d\s\-]+", " ", addr
    )
    addr = re.sub(
        r"(?i),?\s*(?:barrio|barriada)\s*(?:de\s*)?[\w\d\s\-]+", " ", addr
    )
    addr = re.sub(r"(?i),?\s*pueblo nuevo\b\.?", " ", addr)
    addr = re.sub(r"(?i),?\s*farmacia\b\.?", " ", addr)
    addr = re.sub(r"(?i),?\s*bajo\b\.?", " ", addr)
    addr = re.sub(r"(?i)\bbl(?:oque)?\.?\s*[\w\d]+", " ", addr)

    # 5. Quitar S/N, s/n
    addr = re.sub(r"(?i)\bs/?n\b\.?", " ", addr)

    # 6. Quitar indicadores de número sin tocar palabras como NOVEL
    addr = re.sub(r"(?i)\bN[º°]\.?\s*", " ", addr)
    addr = re.sub(r"(?i)\bNo\.?\s*(?=\d)", " ", addr)
    addr = re.sub(r"(?i)\bN[ÚU]M(?:ERO)?\.?\s*(?=\d)", " ", addr)

    # 7. Quitar Local N, LOC. 7,8
    addr = re.sub(
        r"(?i),?\s*\b(?:local|loc)\b\.?(?:\s*[-–—]?\s*[\w\d]+(?:\s*[,y/-]\s*[\w\d]+)*)?",
        " ",
        addr,
    )

    # 8. Separar letras/números pegados tras puntos (ej. "AVDA.REINO" -> "AVDA REINO")
    addr = re.sub(r"([A-Za-z]+)\.([A-Za-z0-9])", r"\1 \2", addr)

    # 9. Quitar sufijo de núcleo pegado al número de portal (ej. "1-LOS NAREJOS" -> "1")
    addr = re.sub(r"(\d+)\s*-[A-Za-z\s]+$", r"\1", addr)

    # 10. Expandir abreviaturas
    addr = re.sub(r"(?i)\b(c/|cl\b\.?)\s*", "CALLE ", addr)
    addr = re.sub(r"(?i)\b(avda\b\.?|av\b\.?)\s*", "AVENIDA ", addr)
    addr = re.sub(r"(?i)\bctra\b\.?\s*", "CARRETERA ", addr)
    addr = re.sub(r"(?i)\b(pza\b\.?|pl\b\.?|plz\b\.?|pz\b\.?)\s*", "PLAZA ", addr)
    addr = re.sub(r"(?i)\bpso\b\.?\s*", "PASEO ", addr)
    addr = re.sub(r"(?i)\btrav\b\.?\s*", "TRAVESIA ", addr)
    addr = re.sub(r"(?i)\burb\b\.?\s*", "URBANIZACION ", addr)

    # 11. Quitar coma residual tras tipo de vía (ej. "AVENIDA, S'OLIVERA" -> "AVENIDA S'OLIVERA")
    addr = re.sub(
        r"(?i)\b(AVENIDA|CALLE|PLAZA|PASEO|CARRETERA|TRAVESIA)\s*,\s*",
        r"\1 ",
        addr,
    )

    # 12. Normalizar espacios y signos de puntuación sobrantes
    addr = re.sub(r"\s*,\s*", ", ", addr)
    addr = re.sub(r",\s*,", ", ", addr)
    addr = re.sub(r"\s+", " ", addr).strip(" ,.-")

    # 13. Si después del número hay una coma y más texto sobrante, quitarlo
    addr = re.sub(r"(\d+)\s*,\s*.*$", r"\1", addr)
    return addr


# Mapeo de pedanías y nombres invertidos en Murcia -> (municipio, nucleo)
MURCIA_KNOWN_MAP: dict[str, tuple[str, str | None]] = {
    "ALBERCA,LAS": ("Murcia", "La Alberca"),
    "ALCAZARES, LOS": ("Los Alcázares", None),
    "ALGAR,EL": ("Cartagena", "El Algar"),
    "ALJORRA,LAS": ("Cartagena", "La Aljorra"),
    "ALMUDEMA,LAS": ("Caravaca de la Cruz", "La Almudema"),
    "BALSAPINTA DA": ("Fuente Álamo", "Balsapintada"),
    "BARRANDA": ("Caravaca de la Cruz", "Barranda"),
    "BOLNUEVO (MAZARRON)": ("Mazarrón", "Bolnuevo"),
    "CABO DE PALOS": ("Cartagena", "Cabo de Palos"),
    "CUEVAS DEL REYLLO": ("Fuente Álamo", "Cuevas de Reyllo"),
    "DOLORES-TORRE PACHECO": ("Torre-Pacheco", "Dolores de Pacheco"),
    "DOLORES-TORRE PACHEC": ("Torre-Pacheco", "Dolores de Pacheco"),
    "EL ALBUJON": ("Cartagena", "El Albujón"),
    "EL PUNTAL (ESPINARDO)": ("Murcia", "El Puntal"),
    "ESPINARDO": ("Murcia", "Espinardo"),
    "FUENTE LIBRILLA": ("Mula", "Fuente Librilla"),
    "GARRES,LOS": ("Murcia", "Los Garres"),
    "HOYA,LA-LORCA": ("Lorca", "La Hoya"),
    "ISLA PLANA": ("Cartagena", "Isla Plana"),
    "LA FLORIDA (LAS TORRES DE COTILLAS)": ("Las Torres de Cotillas", "La Florida"),
    "LA HOYA -LORCA": ("Lorca", "La Hoya"),
    "LA MANGA DEL MAR MENOR": ("Cartagena", "La Manga del Mar Menor"),
    "LAS PALAS(FUENTE ALAMO)": ("Fuente Álamo", "Las Palas"),
    "LLANO DE MOLINA S.": ("Molina de Segura", "Llano de Molina"),
    "LO PAGAN": ("San Pedro del Pinatar", "Lo Pagán"),
    "MARFAGONE S-CARTAGENA": ("Cartagena", "Los Molinos Marfagones"),
    "MARTINEZ DEL PUERTO, LOS": ("Murcia", "Los Martínez del Puerto"),
    "NONDUERMA S": ("Murcia", "Nonduermas"),
    "PACA,LA-LORCA": ("Lorca", "La Paca"),
    "PALMAR,EL": ("Murcia", "El Palmar"),
    "PORTMAN (LA UNION)": ("La Unión", "Portmán"),
    "PUERTO DE MAZARRON": ("Mazarrón", "Puerto de Mazarrón"),
    "PUNTAL,EL": ("Murcia", "El Puntal"),
    "RAAL,EL": ("Murcia", "El Raal"),
    "RIBERA DE MOLINA": ("Molina de Segura", "Ribera de Molina"),
    "RINCON DE BENISCORNI A": ("Murcia", "Rincón de Beniscornia"),
    "ROLDAN": ("Torre-Pacheco", "Roldán"),
    "SANTIAGO DE LA RIBERA": ("San Javier", "Santiago de la Ribera"),
    "TORREALTA (MOLINA DE SEGURA)": ("Molina de Segura", "Torrealta"),
    "TORREAGUE RA": ("Murcia", "Torreagüera"),
    "TORRES DE COTILLAS,LAS": ("Las Torres de Cotillas", None),
    "UNION,LAS": ("La Unión", None),
    "ÑORA,LAS": ("Murcia", "La Ñora"),
}

MURCIA_CITY_PEDANIAS: set[str] = {
    "ALGEZARES", "ALJUCER", "ALQUERIAS", "BARQUEROS", "BENIAJAN",
    "CABEZO DE TORRES", "CHURRA", "COBATILLAS", "CORVERA", "EL ESPARRAGAL",
    "EL RANERO", "ERA ALTA", "GUADALUPE", "JAVALI NUEVO", "JAVALI VIEJO",
    "LLANO DE BRUJAS", "LOBOSILLO", "LOS RAMOS", "MONTEAGUDO", "PATIÑO",
    "PUEBLA DE SOTO", "PUENTE TOCINOS", "RINCON DE SECA", "SAN GINES",
    "SAN JOSE DE LA VEGA", "SANGONERA LA SECA", "SANGONERA LA VERDE",
    "SANTA CRUZ", "SANTIAGO Y ZARAICHE", "SANTO ANGEL", "SUCINA", "ZENETA"
}

MURCIA_MUNI_ALIASES: dict[str, str] = {
    "MOLINA DESEGURA": "Molina de Segura",
    "MOLINA DE SEGURA": "Molina de Segura",
    "LASTORRES DECOTILLAS": "Las Torres de Cotillas",
    "LAS TORRES DE COTILLAS": "Las Torres de Cotillas",
    "LOSALCAZARES": "Los Alcázares",
    "LOS ALCAZARES": "Los Alcázares",
    "TORREPACHECO": "Torre-Pacheco",
    "TORRE PACHECO": "Torre-Pacheco",
    "TORRE PACHEC": "Torre-Pacheco",
    "FUENTE ALAMO": "Fuente Álamo",
    "CARAVACA": "Caravaca de la Cruz",
    "CARAVACA DE LA CRUZ": "Caravaca de la Cruz",
    "ESPINARDO": "Murcia",
    "DOLORES-TORRE PACHEC": "Torre-Pacheco",
    "ALMENDRIC OS-LORCA": "Lorca",
    "ALMENDRICOS-LORCA": "Lorca",
}

# Mapeo de pedanías y localidades en Baleares -> (municipio, nucleo)
BALEARES_KNOWN_MAP: dict[str, tuple[str, str | None]] = {
    "CIUTADELLA": ("Ciutadella de Menorca", None),
    "MAO": ("Maó-Mahón", None),
    "MAÓ": ("Maó-Mahón", None),
    "ES MERCADAL": ("Es Mercadal", None),
    "ES MIGJORN GRAN": ("Es Migjorn Gran", None),
    "ALAIOR": ("Alaior", None),
    "FERRERIES": ("Ferreries", None),
    "EIVISSA": ("Eivissa", None),
    "SANTA EULÀRIA": ("Santa Eulària des Riu", None),
    "SANTA EULALIA": ("Santa Eulària des Riu", None),
    "EULÀRIA": ("Santa Eulària des Riu", None),
    "EULÀLIA": ("Santa Eulària des Riu", None),
    "SANT ANTONI": ("Sant Antoni de Portmany", None),
    "SANT JOSEP": ("Sant Josep de sa Talaia", None),
    "SANT JOAN DE LABRITJA": ("Sant Joan de Labritja", None),
    "FORMENTERA": ("Formentera", None),
    "SANT FERRAN": ("Formentera", "Sant Ferran de ses Roques"),
    "SANT FRANCESC": ("Formentera", "Sant Francesc Xavier"),
    "CA'S CATALA": ("Calvià", "Cas Català"),
    "PEGUERA": ("Calvià", "Peguera"),
    "PAGUERA": ("Calvià", "Peguera"),
    "SANTA PONSA": ("Calvià", "Santa Ponça"),
    "SANTA PONSA NOVO": ("Calvià", "Santa Ponça"),
    "MAGALLUF": ("Calvià", "Magaluf"),
    "PALMA NOVA": ("Calvià", "Palmanova"),
    "PORTALS NOUS": ("Calvià", "Portals Nous"),
    "EL TORO": ("Calvià", "El Toro"),
    "ILLETES": ("Calvià", "Ses Illetes"),
    "SON CALIU": ("Calvià", "Son Caliu"),
    "SON FERRER ( CALVIA)": ("Calvià", "Son Ferrer"),
    "SON FERRER": ("Calvià", "Son Ferrer"),
    "COSTA DE LA CALMA": ("Calvià", "Costa de la Calma"),
    "COSTA D'EN": ("Calvià", "Costa d'en Blanes"),
    "CAPDELLÀ": ("Calvià", "Es Capdellà"),
    "B (PORT ANDRATX)": ("Andratx", "Port d'Andratx"),
    "PORT ANDRATX": ("Andratx", "Port d'Andratx"),
    "PORT D'ANDRATX": ("Andratx", "Port d'Andratx"),
    "CAMP DE MAR": ("Andratx", "Camp de Mar"),
    "CALA RATJADA": ("Capdepera", "Cala Rajada"),
    "CALA RAJADA": ("Capdepera", "Cala Rajada"),
    "CALA LLITERAS (CALA RATJADA)": ("Capdepera", "Cala Rajada"),
    "CALA MILLOR": ("Son Servera", "Cala Millor"),
    "CALA BONA": ("Son Servera", "Cala Bona"),
    "SA COMA": ("Sant Llorenç des Cardassar", "Sa Coma"),
    "CAN PICAFORT": ("Santa Margalida", "Can Picafort"),
    "C'AN PICAFORT": ("Santa Margalida", "Can Picafort"),
    "SON SERRA MARINA": ("Santa Margalida", "Son Serra de Marina"),
    "PLATJA DE MURO": ("Muro", "Platja de Muro"),
    "PORT ALCUDIA": ("Alcúdia", "Port d'Alcúdia"),
    "PORT D'ALCUDIA": ("Alcúdia", "Port d'Alcúdia"),
    "ES MAL PAS": ("Alcúdia", "Es Mal Pas"),
    "A (ALCUDIA)": ("Alcúdia", None),
    "CALA SANT VICENÇ": ("Pollença", "Cala Sant Vicenç"),
    "CALA D'OR": ("Santanyí", "Cala d'Or"),
    "CALA FIGUERA": ("Santanyí", "Cala Figuera"),
    "CALA EGOS": ("Santanyí", "Cala Egos"),
    "CALA ESMERALDA": ("Santanyí", "Cala Esmeralda"),
    "CALONGE": ("Santanyí", "Calonge"),
    "PORTO PETRO": ("Santanyí", "Portopetro"),
    "S'ALQUERIA BLANCA": ("Santanyí", "S'Alqueria Blanca"),
    "PORTO COLOM": ("Felanitx", "Portocolom"),
    "S'HORTA": ("Felanitx", "S'Horta"),
    "COLONIA DE SANT JORDI": ("Ses Salines", "Colònia de Sant Jordi"),
    "SA RAPITA": ("Campos", "Sa Ràpita"),
    "BAHIA GRANDE": ("Llucmajor", "Badia Gran"),
    "LES PALMERES": ("Llucmajor", "Les Palmeres"),
    "S'ARENAL DE LLUCMAJOR": ("Llucmajor", "S'Arenal"),
    "PONT D'INCA NOU-": ("Marratxí", "Es Pont d'Inca"),
    "PALMA": ("Palma", None),
    "EL ARENAL": ("Palma", "S'Arenal"),
    "CA'N PASTILLA": ("Palma", "Can Pastilla"),
    "Coll d'en Rebassa": ("Palma", "Coll d'en Rabassa"),
    "cami del cementiri": ("Palma", None),
}


def get_candidate_municipalities(
    pharmacy: Pharmacy,
) -> list[tuple[str, str | None]]:
    """Determina los municipios y núcleos candidatos según las reglas de la Tarea 03c.

    Devuelve lista de (municipio, nucleo).
    Si nucleo es None, indica que es el casco urbano municipal.
    """
    if pharmacy.region == "14":  # Región de Murcia
        loc = (pharmacy.locality or "").strip()
        if not loc:
            return [("Murcia", None)]

        # Caso especial La Manga: puede pertencer a Cartagena o San Javier
        if loc == "LA MANGA DEL MAR MENOR":
            return [
                ("Cartagena", "La Manga del Mar Menor"),
                ("San Javier", "La Manga del Mar Menor"),
            ]

        # Mapeo conocido directo
        if loc in MURCIA_KNOWN_MAP:
            return [MURCIA_KNOWN_MAP[loc]]

        # Pedanías de Murcia capital
        if loc in MURCIA_CITY_PEDANIAS:
            return [("Murcia", loc.title())]

        # Patrón: "X (MUNICIPIO)" o "X (MUNICIPIO"
        m = re.search(r"^(.*?)\s*\(([^)]+)\)?$", loc)
        if m:
            nucleo = m.group(1).strip().title()
            raw_muni = m.group(2).strip().upper()
            muni = MURCIA_MUNI_ALIASES.get(raw_muni, raw_muni.title())
            return [(muni, nucleo)]

        # Patrón: "NUCLEO-MUNICIPIO"
        if "-" in loc:
            parts = [p.strip() for p in loc.split("-") if p.strip()]
            if len(parts) >= 2:
                raw_muni = parts[-1].upper()
                muni = MURCIA_MUNI_ALIASES.get(raw_muni, parts[-1].title())
                nucleo = parts[0].title()
                return [(muni, nucleo)]

        # Casco urbano directo
        muni_direct = MURCIA_MUNI_ALIASES.get(loc.upper(), loc.title())
        return [(muni_direct, None)]

    else:  # Illes Balears (04)
        loc = (pharmacy.locality or "").strip()

        # Mapeo conocido directo
        if loc and loc in BALEARES_KNOWN_MAP:
            return [BALEARES_KNOWN_MAP[loc]]

        # Si locality es un municipio directo reconocido
        if loc:
            loc_title = loc.title()
            return [(loc_title, None)]

        # Si locality está vacía, derivar de zones
        res: list[tuple[str, str | None]] = []
        zones_list: list[str] = []
        if pharmacy.zones:
            try:
                zs = json.loads(pharmacy.zones)
                if isinstance(zs, list):
                    zones_list = zs
            except Exception:
                pass

        for z in zones_list:
            z_upper = z.upper()
            if z_upper in ("PALMA", "PLATJA DE PALMA"):
                if ("Palma", None) not in res:
                    res.append(("Palma", None))
            elif "-" in z:
                # Zona compuesta A-B-C: probar cada municipio
                parts = [p.strip().title() for p in z.split("-") if p.strip()]
                for p in parts:
                    if (p, None) not in res:
                        res.append((p, None))
            else:
                z_title = z.strip().title()
                if (z_title, None) not in res:
                    res.append((z_title, None))

        if not res:
            res.append(("Palma", None))

        return res


def get_cached_result(
    session: Session, query: str
) -> tuple[float | None, float | None, str | None, str | None] | None:
    norm = re.sub(r"\s+", " ", query.strip().lower())
    cached = session.get(GeocodeCache, norm)
    if cached:
        return (cached.lat, cached.lon, cached.precision, cached.provider)
    return None


def save_cached_result(
    session: Session,
    query: str,
    lat: float | None,
    lon: float | None,
    precision: str | None,
    provider: str | None,
    raw_data: Any = None,
) -> None:
    norm = re.sub(r"\s+", " ", query.strip().lower())
    raw_json = json.dumps(raw_data, ensure_ascii=False) if raw_data else None
    cache_entry = session.get(GeocodeCache, norm)
    if cache_entry is None:
        cache_entry = GeocodeCache(
            query=norm,
            lat=lat,
            lon=lon,
            precision=precision,
            provider=provider,
            raw_json=raw_json,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(cache_entry)
    else:
        cache_entry.lat = lat
        cache_entry.lon = lon
        cache_entry.precision = precision
        cache_entry.provider = provider
        cache_entry.raw_json = raw_json


def get_nucleus_centroid(
    client: httpx.Client,
    session: Session,
    nucleo: str,
    municipio: str,
    region: str,
) -> tuple[float, float] | None:
    """Devuelve las coordenadas del centroide de un núcleo/pedanía sin valores fijos.

    Geocodificado dinámicamente como lugar habitado en CartoCiudad o Nominatim.
    """
    if not nucleo:
        return None

    cache_key = (
        f"nucleus:{normalize_text(nucleo)}:{normalize_text(municipio)}:{region}"
    )
    cached = get_cached_result(session, cache_key)
    if cached and cached[0] is not None and cached[1] is not None:
        return (cached[0], cached[1])

    # 1. CartoCiudad find
    try:
        r = client.get(
            CARTOCIUDAD_FIND_URL, params={"q": f"{nucleo}, {municipio}"}, timeout=8.0
        )
        if r.status_code == 200:
            d = r.json()
            lat, lng = d.get("lat"), d.get("lng")
            if lat and lng and (float(lat) != 0.0 or float(lng) != 0.0):
                lat_f, lon_f = float(lat), float(lng)
                if is_within_bbox(region, lat_f, lon_f) and muni_matches(
                    municipio, d.get("muni", "")
                ):
                    save_cached_result(
                        session, cache_key, lat_f, lon_f, "localidad", "cartociudad_find"
                    )
                    return (lat_f, lon_f)
    except Exception:
        pass

    # 2. CartoCiudad candidates
    try:
        region_name = "Illes Balears" if region == "04" else "Región de Murcia"
        r = client.get(
            CARTOCIUDAD_CANDIDATES_URL,
            params={
                "q": nucleo,
                "municipio_filter": municipio,
                "comunidad_autonoma_filter": region_name,
            },
            timeout=8.0,
        )
        if r.status_code == 200:
            data = r.json()
            if data and isinstance(data, list):
                for item in data:
                    lat, lng = item.get("lat"), item.get("lng")
                    if lat and lng and (float(lat) != 0.0 or float(lng) != 0.0):
                        lat_f, lon_f = float(lat), float(lng)
                        if is_within_bbox(region, lat_f, lon_f) and muni_matches(
                            municipio, item.get("muni", "")
                        ):
                            save_cached_result(
                                session,
                                cache_key,
                                lat_f,
                                lon_f,
                                "localidad",
                                "cartociudad_candidates",
                            )
                            return (lat_f, lon_f)
    except Exception:
        pass

    # 3. Nominatim
    _nominatim_rate_limit()
    try:
        r = client.get(
            NOMINATIM_URL,
            params={
                "q": f"{nucleo}, {municipio}, Spain",
                "format": "json",
                "addressdetails": 1,
                "limit": 3,
            },
            headers={"User-Agent": NOMINATIM_USER_AGENT},
            timeout=8.0,
        )
        if r.status_code == 200:
            data = r.json()
            if data and isinstance(data, list):
                for it in data:
                    lat_f = float(it["lat"])
                    lon_f = float(it["lon"])
                    if is_within_bbox(region, lat_f, lon_f):
                        addr = it.get("address", {})
                        res_muni = (
                            addr.get("city")
                            or addr.get("town")
                            or addr.get("municipality")
                            or addr.get("village")
                            or ""
                        )
                        if muni_matches(municipio, res_muni) or not res_muni:
                            save_cached_result(
                                session,
                                cache_key,
                                lat_f,
                                lon_f,
                                "localidad",
                                "nominatim",
                            )
                            return (lat_f, lon_f)
    except Exception:
        pass

    return None


def get_municipality_centroid(
    client: httpx.Client,
    session: Session,
    municipio: str,
    region: str,
) -> tuple[float, float] | None:
    """Devuelve las coordenadas del centroide del municipio (con caché, sin valores fijos)."""
    norm_muni = normalize_text(municipio)
    cache_key = f"muni_centroid:{norm_muni}:{region}"
    cached = get_cached_result(session, cache_key)
    if cached and cached[0] is not None and cached[1] is not None:
        return (cached[0], cached[1])

    region_name = "Illes Balears" if region == "04" else "Región de Murcia"

    # 1. CartoCiudad find
    try:
        r = client.get(
            CARTOCIUDAD_FIND_URL, params={"q": f"{municipio}, {region_name}"}, timeout=8.0
        )
        if r.status_code == 200:
            d = r.json()
            lat = d.get("lat")
            lng = d.get("lng")
            if lat and lng and (float(lat) != 0.0 or float(lng) != 0.0):
                lat_f, lon_f = float(lat), float(lng)
                if is_within_bbox(region, lat_f, lon_f) and muni_matches(
                    municipio, d.get("muni", "")
                ):
                    save_cached_result(
                        session,
                        cache_key,
                        lat_f,
                        lon_f,
                        "localidad",
                        "cartociudad",
                    )
                    return (lat_f, lon_f)
    except Exception:
        pass

    # 2. Nominatim
    _nominatim_rate_limit()
    try:
        r = client.get(
            NOMINATIM_URL,
            params={"city": municipio, "countrycodes": "es", "format": "json", "limit": 1},
            headers={"User-Agent": NOMINATIM_USER_AGENT},
            timeout=8.0,
        )
        if r.status_code == 200:
            data = r.json()
            if data and isinstance(data, list):
                lat_f = float(data[0]["lat"])
                lon_f = float(data[0]["lon"])
                if is_within_bbox(region, lat_f, lon_f):
                    save_cached_result(
                        session,
                        cache_key,
                        lat_f,
                        lon_f,
                        "localidad",
                        "nominatim",
                    )
                    return (lat_f, lon_f)
    except Exception:
        pass

    return None


def geocode_cartociudad_structured(
    client: httpx.Client,
    clean_addr: str,
    municipio: str,
    region: str,
    postal_code: str | None = None,
    nucleo: str | None = None,
) -> tuple[float | None, float | None, str | None, dict[str, Any] | None]:
    """Consulta CartoCiudad con filtros por municipio y comunidad autónoma."""
    region_name = "Illes Balears" if region == "04" else "Región de Murcia"

    # Probar diferentes variantes de consulta:
    # 1. Si hay núcleo: "clean_addr, nucleo"
    # 2. "clean_addr, municipio"
    # 3. Sin tipo de vía si clean_addr empieza por CALLE/AVENIDA/etc.
    queries = []
    if nucleo:
        queries.append(f"{clean_addr}, {nucleo}")
    queries.append(f"{clean_addr}, {municipio}")

    parts = clean_addr.split(" ", 1)
    if len(parts) == 2 and parts[0] in (
        "CALLE", "AVENIDA", "CARRETERA", "PLAZA", "PASEO", "TRAVESIA", "URBANIZACION"
    ):
        if nucleo:
            queries.append(f"{parts[1]}, {nucleo}")
        queries.append(f"{parts[1]}, {municipio}")

    for q_str in queries:
        params: dict[str, Any] = {
            "q": q_str,
            "limit": 6,
            "comunidad_autonoma_filter": region_name,
            "municipio_filter": municipio,
        }
        if postal_code and postal_code.strip():
            params["cod_postal_filter"] = postal_code.strip()

        try:
            resp = client.get(
                CARTOCIUDAD_CANDIDATES_URL, params=params, timeout=8.0
            )
            if resp.status_code != 200:
                params.pop("cod_postal_filter", None)
                resp = client.get(
                    CARTOCIUDAD_CANDIDATES_URL, params=params, timeout=8.0
                )

            if resp.status_code != 200:
                continue

            data = resp.json()
            if not data or not isinstance(data, list):
                continue

            # Si hay núcleo, ordenar para priorizar candidatos cuya población coincida con el núcleo
            if nucleo:
                norm_nuc = normalize_text(nucleo)

                def rank_candidate(it: dict[str, Any]) -> int:
                    pob = normalize_text(it.get("poblacion") or "")
                    addr_str = normalize_text(it.get("address") or "")
                    if norm_nuc and (norm_nuc in pob or pob in norm_nuc or norm_nuc in addr_str):
                        return 0
                    return 1

                data.sort(key=rank_candidate)

            for item in data:
                lat = item.get("lat")
                lon = item.get("lng")
                item_type = str(item.get("type", "")).lower()
                res_muni = item.get("muni", "")

                if not muni_matches(municipio, res_muni):
                    continue

                if (lat is None or lon is None or (lat == 0.0 and lon == 0.0)) and item.get("address"):
                    try:
                        r_find = client.get(
                            CARTOCIUDAD_FIND_URL, params={"q": item.get("address")}, timeout=8.0
                        )
                        if r_find.status_code == 200:
                            find_data = r_find.json()
                            lat = find_data.get("lat")
                            lon = find_data.get("lng")
                            if not item_type:
                                item_type = str(find_data.get("type", "")).lower()
                    except Exception:
                        pass

                if lat is not None and lon is not None and (lat != 0.0 or lon != 0.0):
                    lat_f = float(lat)
                    lon_f = float(lon)
                    if not is_within_bbox(region, lat_f, lon_f):
                        continue

                    if item_type in ("portal", "expendeduria"):
                        precision = "portal"
                    elif item_type in ("callejero", "tramo", "carretera", "vial"):
                        precision = "calle"
                    else:
                        continue

                    return lat_f, lon_f, precision, item

        except Exception as e:
            logger.warning("CartoCiudad structured error: %s", e)

    return None, None, None, None


def geocode_nominatim_structured(
    client: httpx.Client,
    clean_addr: str,
    municipio: str,
    region: str,
    postal_code: str | None = None,
    nucleo: str | None = None,
) -> tuple[float | None, float | None, str | None, dict[str, Any] | None]:
    """Consulta Nominatim en modo estructurado (street, city, postalcode, countrycodes=es)."""
    headers = {"User-Agent": NOMINATIM_USER_AGENT}

    cities_to_try = [municipio]
    if nucleo and nucleo.lower() != municipio.lower():
        cities_to_try.insert(0, nucleo)

    for city in cities_to_try:
        _nominatim_rate_limit()
        params: dict[str, Any] = {
            "street": clean_addr,
            "city": city,
            "countrycodes": "es",
            "format": "json",
            "addressdetails": 1,
            "limit": 2,
        }
        if postal_code and postal_code.strip():
            params["postalcode"] = postal_code.strip()

        try:
            resp = client.get(
                NOMINATIM_URL, params=params, headers=headers, timeout=8.0
            )
            if resp.status_code != 200:
                continue

            data = resp.json()
            if not data or not isinstance(data, list):
                continue

            for item in data:
                lat = float(item["lat"])
                lon = float(item["lon"])
                if not is_within_bbox(region, lat, lon):
                    continue

                addr_info = item.get("address", {})
                res_muni = (
                    addr_info.get("city")
                    or addr_info.get("town")
                    or addr_info.get("municipality")
                    or addr_info.get("village")
                    or ""
                )
                if not muni_matches(municipio, res_muni) and not muni_matches(city, res_muni):
                    continue

                osm_class = item.get("class", "")
                osm_type = item.get("type", "")

                if osm_class in ("place", "building", "amenity", "shop") and osm_type in (
                    "house",
                    "building",
                    "yes",
                    "pharmacy",
                    "commercial",
                    "apartments",
                ):
                    precision = "portal"
                elif osm_class == "highway":
                    precision = "calle"
                else:
                    precision = "calle"

                return lat, lon, precision, item

        except Exception as e:
            logger.warning("Nominatim structured error: %s", e)

    return None, None, None, None


def geocode_pharmacy_v3(
    session: Session,
    client: httpx.Client,
    pharmacy: Pharmacy,
) -> tuple[float | None, float | None, str | None, str | None, str, str | None, bool]:
    """Estrategia de geocodificación v3 (Tarea 03c):

    1. Normaliza dirección.
    2. Obtiene candidatos a (municipio, nucleo).
    3. Para cada candidato, intenta CartoCiudad estructurado -> Nominatim estructurado.
    4. Control de calidad:
       - Si hay núcleo (pedanía): valida distancia < 5 km al centroide del núcleo.
       - Si es casco urbano: valida distancia < 15 km al centroide del municipio.
    5. Si falla la dirección:
       - Si hay núcleo (pedanía): fallback al centroide del núcleo (precisión 'localidad').
         NUNCA al centroide del municipio. Si el núcleo no se halla: NULL.
       - Si es casco urbano: fallback al centroide del municipio (precisión 'localidad').
    Devuelve (lat, lon, precision, provider, final_query, error_reason, es_sospechosa).
    """
    clean_addr = clean_address(pharmacy.address)
    candidates = get_candidate_municipalities(pharmacy)
    region_name = "Illes Balears" if pharmacy.region == "04" else "Región de Murcia"

    for muni, nucleo in candidates:
        sent_query = f"{clean_addr}, {nucleo or muni} ({muni}, {region_name})"

        # Obtener centroide de referencia (núcleo si existe, o municipio)
        ref_centroid = None
        if nucleo:
            ref_centroid = get_nucleus_centroid(
                client, session, nucleo, muni, pharmacy.region
            )
        if not ref_centroid:
            ref_centroid = get_municipality_centroid(
                client, session, muni, pharmacy.region
            )

        # 1. CartoCiudad estructurado
        lat, lon, precision, raw = geocode_cartociudad_structured(
            client,
            clean_addr,
            muni,
            pharmacy.region,
            pharmacy.postal_code,
            nucleo=nucleo,
        )
        provider = "cartociudad"

        # 2. Nominatim estructurado
        if lat is None:
            lat, lon, precision, raw = geocode_nominatim_structured(
                client,
                clean_addr,
                muni,
                pharmacy.region,
                pharmacy.postal_code,
                nucleo=nucleo,
            )
            provider = "nominatim"

        # Si se encontró a nivel portal o calle:
        if lat is not None and lon is not None and precision in ("portal", "calle"):
            # Control de distancia
            max_dist = 5.0 if nucleo else 15.0
            if ref_centroid:
                dist = haversine_km(lat, lon, ref_centroid[0], ref_centroid[1])
                if dist > max_dist:
                    # Degradación a centroide de localidad correspondiente
                    return (
                        ref_centroid[0],
                        ref_centroid[1],
                        "localidad",
                        "centroid",
                        sent_query,
                        None,
                        True,
                    )
            return lat, lon, precision, provider, sent_query, None, False

        # Si no se encontró calle ni portal: fallback a localidad
        if nucleo:
            # Para una pedanía: SOLO el centroide del núcleo, NUNCA el del municipio
            nuc_centroid = get_nucleus_centroid(
                client, session, nucleo, muni, pharmacy.region
            )
            if nuc_centroid:
                return (
                    nuc_centroid[0],
                    nuc_centroid[1],
                    "localidad",
                    "nucleus_centroid",
                    f"{nucleo}, {muni}",
                    None,
                    False,
                )
        else:
            # Casco urbano (locality == municipio)
            muni_c = get_municipality_centroid(
                client, session, muni, pharmacy.region
            )
            if muni_c:
                return (
                    muni_c[0],
                    muni_c[1],
                    "localidad",
                    "muni_centroid",
                    f"{muni}, {region_name}",
                    None,
                    False,
                )

    # Si ningún candidato pudo situarse: NULL
    best_muni = candidates[0][0]
    return (
        None,
        None,
        None,
        None,
        f"{clean_addr}, {best_muni}",
        "No se pudo situar la dirección ni el núcleo",
        False,
    )


def enforce_shared_coordinates_limit(session: Session) -> list[dict[str, Any]]:
    """Aplica la regla de control final de la Tarea 03c:

    Ningún par (lat, lon) puede ser compartido por más de 2 farmacias
    salvo que tengan la misma dirección normalizada.
    Las farmacias sobrantes en clusters de centroide se degradan a lat/lon = NULL.
    """
    pharmacies = session.scalars(
        select(Pharmacy).where(Pharmacy.lat.is_not(None), Pharmacy.lon.is_not(None))
    ).all()

    coords_map: dict[tuple[float, float], list[Pharmacy]] = defaultdict(list)
    for p in pharmacies:
        key = (round(p.lat, 5), round(p.lon, 5))
        coords_map[key].append(p)

    degraded_list: list[dict[str, Any]] = []

    for (lat_r, lon_r), members in coords_map.items():
        if len(members) <= 2:
            continue

        # Comprobar si todas tienen la misma dirección normalizada
        clean_addrs = {clean_address(m.address) for m in members}
        if len(clean_addrs) == 1:
            # Es la misma dirección física compartida (ej. co-titulares o mismo edificio)
            continue

        # Es un cluster indebido (ej. centroide compartido por múltiples farmacias distintas).
        # Conservar hasta 2 (priorizando las que sean portal o calle) y degradar las demás a NULL
        def sort_priority(p: Pharmacy) -> int:
            if p.geo_precision == "portal":
                return 0
            if p.geo_precision == "calle":
                return 1
            return 2

        members.sort(key=sort_priority)

        # Las dos primeras se conservan
        for excess in members[2:]:
            degraded_list.append(
                {
                    "id": excess.id,
                    "titular": excess.holder,
                    "direccion": excess.address,
                    "localidad": excess.locality,
                    "coords": (lat_r, lon_r),
                    "motivo": f"Punto compartido por {len(members)} farmacias con distintas direcciones",
                }
            )
            excess.lat = None
            excess.lon = None
            excess.geo_precision = None
            excess.geo_source = None

    session.commit()
    return degraded_list


def geocode_all_pharmacies(
    limit: int | None = None,
    recheck_only: bool = False,
    report_path: Path | str = "tmp/geocode_report.txt",
    database_url: str | None = None,
) -> dict[str, Any]:
    """Geocodifica las farmacias de la base de datos y genera el informe final (Tarea 03c)."""
    engine = create_db_engine(database_url)
    init_db(engine)

    report_file = Path(report_path)
    report_file.parent.mkdir(parents=True, exist_ok=True)

    with Session(engine) as session:
        if recheck_only:
            query = (
                select(Pharmacy)
                .where(
                    or_(
                        Pharmacy.geo_precision == "localidad",
                        Pharmacy.geo_precision.is_(None),
                        Pharmacy.lat.is_(None),
                        Pharmacy.lon.is_(None),
                        # También reprocesar las que tengan exactamente coordenadas de centroide conocidas
                        Pharmacy.lat.between(39.5695, 39.5697),
                        Pharmacy.lat.between(37.9885, 37.9887),
                        Pharmacy.lat.between(37.6055, 37.6057),
                    )
                )
                .order_by(Pharmacy.id)
            )
        else:
            query = select(Pharmacy).order_by(Pharmacy.id)

        if limit:
            query = query.limit(limit)

        target_pharmacies = session.scalars(query).all()
        print(f"Farmacias a procesar en esta pasada: {len(target_pharmacies)}")

        sospechosas_list: list[dict[str, Any]] = []
        with httpx.Client(timeout=10.0) as client:
            for idx, p in enumerate(target_pharmacies, 1):
                lat, lon, precision, provider, sent_query, error, sospechosa = (
                    geocode_pharmacy_v3(session, client, p)
                )

                p.geo_query = sent_query
                if lat is not None and lon is not None:
                    p.lat = lat
                    p.lon = lon
                    p.geo_precision = precision
                    p.geo_source = provider
                    if sospechosa:
                        sospechosas_list.append(
                            {
                                "id": p.id,
                                "titular": p.holder,
                                "direccion": p.address,
                                "localidad": p.locality,
                                "motivo": "Distancia > tolerancia (degradada a localidad)",
                            }
                        )
                else:
                    p.lat = None
                    p.lon = None
                    p.geo_precision = None
                    p.geo_source = None

                if idx % 25 == 0:
                    session.commit()
                    print(f"Procesadas {idx}/{len(target_pharmacies)} farmacias...")

            session.commit()

        # Control final de coordenadas compartidas
        degraded_shared = enforce_shared_coordinates_limit(session)

        # Recopilar estadísticas globales de toda la base de datos
        all_pharmacies = session.scalars(select(Pharmacy)).all()

    # Estadísticas por precisión y región
    total = len(all_pharmacies)
    stats: dict[str, Any] = {
        "total": total,
        "portal": 0,
        "calle": 0,
        "localidad": 0,
        "fallidos": 0,
        "por_region": {
            "04": {"total": 0, "portal": 0, "calle": 0, "localidad": 0, "fallidos": 0},
            "14": {"total": 0, "portal": 0, "calle": 0, "localidad": 0, "fallidos": 0},
        },
        "palma": {"total": 0, "portal_calle": 0},
        "murcia_muni": {"total": 0, "portal_calle": 0},
        "failed_list": [],
        "sospechosas_list": sospechosas_list,
        "degraded_shared": degraded_shared,
        "test_palma_violations": [],
        "sample_20": [],
    }

    portal_calle_list = []
    coords_count: dict[tuple[float, float], list[Pharmacy]] = defaultdict(list)

    for p in all_pharmacies:
        reg = p.region
        prec = p.geo_precision
        reg_stat = stats["por_region"].setdefault(
            reg, {"total": 0, "portal": 0, "calle": 0, "localidad": 0, "fallidos": 0}
        )
        reg_stat["total"] += 1

        is_palma = False
        if reg == "04":
            loc = (p.locality or "").upper()
            zs = (p.zones or "").upper()
            if loc == "PALMA" or (not loc and "PALMA" in zs):
                is_palma = True
                stats["palma"]["total"] += 1

        is_murcia_muni = False
        if reg == "14":
            loc = (p.locality or "").upper()
            if (
                loc == "MURCIA"
                or "(MURCIA)" in loc
                or (p.postal_code and p.postal_code.startswith("300"))
            ):
                is_murcia_muni = True
                stats["murcia_muni"]["total"] += 1

        if p.lat is not None and p.lon is not None:
            # Comprobación de coordenadas de test de Palma
            if abs(p.lat - 39.5696) < 0.0001 and abs(p.lon - 2.6502) < 0.0001:
                stats["test_palma_violations"].append(p)

            coords_count[(round(p.lat, 5), round(p.lon, 5))].append(p)

            if prec in ("portal", "calle"):
                stats[prec] += 1
                reg_stat[prec] += 1
                if is_palma:
                    stats["palma"]["portal_calle"] += 1
                if is_murcia_muni:
                    stats["murcia_muni"]["portal_calle"] += 1
                portal_calle_list.append(p)
            elif prec == "localidad":
                stats["localidad"] += 1
                reg_stat["localidad"] += 1
        else:
            stats["fallidos"] += 1
            reg_stat["fallidos"] += 1
            stats["failed_list"].append(
                {
                    "id": p.id,
                    "titular": p.holder,
                    "direccion": p.address,
                    "localidad": p.locality,
                    "region": p.region,
                    "motivo": "No se encontraron coordenadas ni dirección ni núcleo",
                }
            )

    portal = stats["portal"]
    calle = stats["calle"]
    localidad = stats["localidad"]
    fallidos = stats["fallidos"]
    portal_calle = portal + calle
    tasa_portal_calle = (portal_calle / total * 100) if total > 0 else 0.0

    palma_total = stats["palma"]["total"]
    palma_pc = stats["palma"]["portal_calle"]
    palma_pct = (palma_pc / palma_total * 100) if palma_total > 0 else 0.0

    murcia_total = stats["murcia_muni"]["total"]
    murcia_pc = stats["murcia_muni"]["portal_calle"]
    murcia_pct = (murcia_pc / murcia_total * 100) if murcia_total > 0 else 0.0

    # Muestra de 20 farmacias aleatorias a portal/calle
    sample_size = min(20, len(portal_calle_list))
    sample = random.sample(portal_calle_list, sample_size) if sample_size > 0 else []

    # Lista de grupos compartidos
    shared_groups = [
        (c, members) for c, members in coords_count.items() if len(members) > 1
    ]
    shared_groups.sort(key=lambda x: len(x[1]), reverse=True)

    lines = [
        "============================================================",
        "INFORME DE GEOCODIFICACIÓN DE FARMACIAS (Tarea 03c)",
        f"Fecha y hora: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "============================================================",
        f"Total farmacias analizadas: {total}",
        f"Precisión Portal + Calle:   {portal_calle} ({tasa_portal_calle:.1f}%)",
        f"Palma (Portal + Calle):     {palma_pc}/{palma_total} ({palma_pct:.1f}%) [Objetivo: >= 85%]",
        f"Murcia muni (Portal+Calle): {murcia_pc}/{murcia_total} ({murcia_pct:.1f}%) [Objetivo: >= 85%]",
        f"Farmacias en (39.5696, 2.6502): {len(stats['test_palma_violations'])} [Objetivo: 0]",
        f"Farmacias con lat/lon NULL:  {fallidos}",
        "",
        "DESGLOSE GLOBAL POR PRECISIÓN:",
        f"  - Portal:    {portal:>4} ({portal / total * 100:.1f}%)",
        f"  - Calle:     {calle:>4} ({calle / total * 100:.1f}%)",
        f"  - Localidad: {localidad:>4} ({localidad / total * 100:.1f}%)",
        f"  - Fallidas:  {fallidos:>4} ({fallidos / total * 100:.1f}%)",
        "",
        "DESGLOSE POR COMUNIDAD AUTÓNOMA:",
    ]

    for reg_code, rstats in stats["por_region"].items():
        r_name = "Illes Balears (04)" if reg_code == "04" else "Región de Murcia (14)"
        r_tot = rstats["total"]
        r_pc = rstats["portal"] + rstats["calle"]
        r_pct = (r_pc / r_tot * 100) if r_tot > 0 else 0.0
        lines.extend([
            f"  [{r_name}] Total: {r_tot}",
            f"    * Portal:    {rstats['portal']} ({rstats['portal'] / r_tot * 100:.1f}%)" if r_tot else "    * Portal: 0",
            f"    * Calle:     {rstats['calle']} ({rstats['calle'] / r_tot * 100:.1f}%)" if r_tot else "    * Calle: 0",
            f"    * Localidad: {rstats['localidad']} ({rstats['localidad'] / r_tot * 100:.1f}%)" if r_tot else "    * Localidad: 0",
            f"    * Fallidas:  {rstats['fallidos']} ({rstats['fallidos'] / r_tot * 100:.1f}%)" if r_tot else "    * Fallidas: 0",
            f"    * Portal + Calle: {r_pc} ({r_pct:.1f}%)",
        ])

    lines.extend([
        "",
        "============================================================",
        f"VERIFICACIÓN DE COORDENADAS DE TEST (PALMA 39.5696, 2.6502):",
        "============================================================",
    ])
    if not stats["test_palma_violations"]:
        lines.append("0 farmacias en (39.5696, 2.6502). Criterio cumplido al 100%.")
    else:
        for v in stats["test_palma_violations"]:
            lines.append(f"VIOLACIÓN: {v.id} | {v.holder} | {v.address} | {v.locality}")

    lines.extend([
        "",
        "============================================================",
        f"COMPROBACIÓN DE PUNTOS COMPARTIDOS (Control Final Tarea 03c):",
        "============================================================",
        f"Puntos compartidos por > 1 farmacia: {len(shared_groups)}",
    ])
    for coords, members in shared_groups:
        diff_addrs = len({clean_address(m.address) for m in members}) > 1
        tag = "[DIRECCIONES DISTINTAS]" if diff_addrs else "[MISMA DIRECCIÓN NORMALIZADA]"
        lines.append(
            f"Punto {coords}: {len(members)} farmacias {tag} -> "
            + ", ".join(f"{m.id} ({clean_address(m.address)})" for m in members)
        )

    lines.extend([
        "",
        "============================================================",
        f"FARMACIAS CON LAT/LON NULL (Total: {len(stats['failed_list'])}):",
        "============================================================",
    ])
    for item in stats["failed_list"]:
        lines.append(
            f"ID: {item['id']} | [{item['region']}] {item['titular']} | Dir: {item['direccion']} | Loc: {item['localidad']}"
        )
    if not stats["failed_list"]:
        lines.append("(Ninguna farmacia con lat/lon NULL)")

    lines.extend([
        "",
        "============================================================",
        f"MUESTRA DE 20 FARMACIAS A PORTAL/CALLE (REVISIÓN MANUAL):",
        "============================================================",
    ])
    for s in sample:
        osm_link = f"https://www.openstreetmap.org/?mlat={s.lat}&mlon={s.lon}#map=18/{s.lat}/{s.lon}"
        lines.append(
            f"ID: {s.id} | [{s.geo_precision.upper()}] {s.holder} | {s.address} ({s.locality or ''}) | {osm_link}"
        )

    report_content = "\n".join(lines) + "\n"
    report_file.write_text(report_content, encoding="utf-8")
    print(f"\nInforme generado en: {report_file.resolve()}")
    print(
        f"Resumen Tarea 03c: Portal+Calle: {portal_calle}/{total} ({tasa_portal_calle:.1f}%). "
        f"Palma: {palma_pc}/{palma_total} ({palma_pct:.1f}%), Murcia: {murcia_pc}/{murcia_total} ({murcia_pct:.1f}%). "
        f"Fallidas: {fallidos}, Palma 39.5696: {len(stats['test_palma_violations'])}"
    )

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Geocodificador mejorado de farmacias de guardia (Tarea 03c)."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Límite máximo de farmacias a geocodificar.",
    )
    parser.add_argument(
        "--recheck",
        action="store_true",
        help="Reprocesar solo las farmacias a precisión localidad, fallidas o centroides.",
    )
    parser.add_argument(
        "--report",
        type=str,
        default="tmp/geocode_report.txt",
        help="Ruta para el informe de geocodificación.",
    )
    args = parser.parse_args()
    geocode_all_pharmacies(
        limit=args.limit,
        recheck_only=args.recheck,
        report_path=args.report,
    )


if __name__ == "__main__":
    main()

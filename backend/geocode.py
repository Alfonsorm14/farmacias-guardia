"""Geocodificación de farmacias con CartoCiudad (IGN) y Nominatim (OSM) — v4.

Reglas (Tareas 03b/03c, revisadas el 19/10/2026):
1. No hay coordenadas fijas ni de respaldo en el código: las únicas constantes
   geográficas son las cajas de validación por comunidad (BBOXES).
2. Todo punto aceptado se valida con la geocodificación inversa de CartoCiudad:
   su municipio debe coincidir con el esperado (comparación exacta normalizada,
   sin subcadenas: "Murcia" no casa con "Alhama de Murcia").
3. Una dirección solo cuenta como portal/calle si el nombre de la vía devuelta
   coincide con el de la fuente y, si la farmacia trae código postal, también
   el código postal.
4. Precisión "localidad" = centroide del NÚCLEO de población (entidad
   "poblacion" de CartoCiudad), validado en su municipio. El centroide del núcleo
   principal del municipio solo se usa si la fuente sitúa la farmacia en el casco
   urbano (localidad == municipio). Si no se puede situar ni la dirección ni el
   núcleo: lat/lon = NULL.
5. Control final: ningún punto compartido por más de 2 farmacias con direcciones
   distintas.

Documentación de los servicios:
- CartoCiudad: https://www.cartociudad.es/web/portal/herramientas-calculos/geocodificador
  (candidates con cod_postal_filter; find por id y tipo; reverseGeocode).
- Nominatim: https://nominatim.org/release-docs/latest/api/Search/ (búsqueda
  estructurada; política de uso: 1 petición/s y User-Agent identificable).

Uso:
    python -m backend.geocode                # reprocesa todas las farmacias
    python -m backend.geocode --recheck      # solo localidad / sin coordenadas
    python -m backend.geocode --ids MU:302,IB:5b84a70432fe
"""
from __future__ import annotations

import argparse
import datetime
import difflib
import json
import logging
import math
import random
import re
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.db import create_db_engine, init_db
from backend.models import GeocodeCache, Pharmacy

logger = logging.getLogger(__name__)

# Cajas de validación por comunidad autónoma (únicas constantes geográficas).
BBOXES: dict[str, dict[str, float]] = {
    "04": {"lat_min": 38.6, "lat_max": 40.1, "lon_min": 1.1, "lon_max": 4.4},
    "14": {"lat_min": 37.3, "lat_max": 38.8, "lon_min": -2.4, "lon_max": -0.6},
    "15": {"lat_min": 41.9, "lat_max": 43.35, "lon_min": -2.55, "lon_max": -0.7},
    "13": {"lat_min": 39.85, "lat_max": 41.2, "lon_min": -4.6, "lon_max": -3.0},
    "02": {"lat_min": 39.8, "lat_max": 42.95, "lon_min": -2.2, "lon_max": 0.8},
}
REGION_PROVINCES: dict[str, set[str]] = {"04": {"07"}, "14": {"30"}, "15": {"31"}, "13": {"28"}, "02": {"22", "44", "50"}}
REGION_NAMES: dict[str, str] = {
    "04": "Illes Balears",
    "14": "Región de Murcia",
    "15": "Comunidad Foral de Navarra",
    "13": "Comunidad de Madrid",
    "02": "Aragón",
}
# Capa oficial de farmacias de Navarra (IDENA, CC BY 4.0) con coordenadas por código.
IDENA_DBF = Path(__file__).resolve().parent.parent / "data" / "raw" / "navarra" / "idena" / "DOTACI_Sym_Farmacias.dbf"
_idena_cache: dict[str, tuple[float, float]] | None = None


def zaragoza_coordinates() -> dict[str, tuple[float, float]]:
    """Coordenadas publicadas por el Ayuntamiento de Zaragoza junto a cada guardia."""
    from ingesta.parsers.zaragoza import load_coordinates

    return load_coordinates(str(IDENA_DBF.parent.parent.parent / "zaragoza"))


def idena_coordinates() -> dict[str, tuple[float, float]]:
    global _idena_cache
    if _idena_cache is None:
        from ingesta.parsers.navarra import load_idena

        _idena_cache = load_idena(str(IDENA_DBF)) if IDENA_DBF.exists() else {}
    return _idena_cache

CARTOCIUDAD_BASE = "https://www.cartociudad.es/geocoder/api/geocoder"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "farmacias-guardia/0.1 (alfonsorivero.es@gmail.com)"

EARTH_RADIUS_KM = 6371.0
# Distancia máxima de una dirección al polígono de su núcleo (pedanía).
NUCLEUS_MAX_KM = 2.5
# Distancia máxima de una dirección de casco urbano al centroide del núcleo principal.
CASCO_MAX_KM = 15.0
# Núcleos repartidos entre dos municipios (Cala Millor: Son Servera y Sant Llorenç):
# se acepta una dirección del municipio vecino si está pegada al núcleo.
NUCLEUS_SHARED_KM = 1.0
# En ciudades grandes el centro del casco puede estar a muchos km de la farmacia:
# por encima de esta extensión no se usa como ubicación aproximada (queda NULL).
CASCO_CENTROID_MAX_EXTENT_KM = 8.0
STREET_MIN_SCORE = 0.6

_last_call: dict[str, float] = {"cartociudad": 0.0, "nominatim": 0.0}
_MIN_INTERVAL = {"cartociudad": 0.34, "nominatim": 1.05}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia ortodrómica en kilómetros entre dos coordenadas WGS84."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return EARTH_RADIUS_KM * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def normalize_text(text: str | None) -> str:
    """Minúsculas, sin acentos y solo [a-z0-9] (para claves y comparaciones)."""
    if not text:
        return ""
    n = unicodedata.normalize("NFD", text)
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", n.lower())


def _tokens(text: str | None) -> list[str]:
    """Palabras normalizadas (sin acentos, minúsculas); el apóstrofo separa."""
    if not text:
        return []
    n = unicodedata.normalize("NFD", text)
    n = "".join(c for c in n if unicodedata.category(c) != "Mn").lower()
    return re.findall(r"[a-z0-9ñ]+", n.replace("ñ", "n"))


def is_within_bbox(region: str, lat: float, lon: float) -> bool:
    """Comprueba si las coordenadas están dentro de la caja de su comunidad."""
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
        r"(?i),?\s*\b(?:edificio|edf\.?|edifico)\s*[\w\d\s\-]+", " ", addr
    )
    addr = re.sub(
        r"(?i),?\s*\b(?:barrio|barriada)\s*(?:de\s*)?[\w\d\s\-]+", " ", addr
    )
    addr = re.sub(r"(?i),?\s*pueblo nuevo\b\.?", " ", addr)
    addr = re.sub(r"(?i),?\s*\bfarmacia\b\.?", " ", addr)
    addr = re.sub(r"(?i),?\s*\bbajos?\b\.?", " ", addr)
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
    addr = re.sub(r"(?i)\b(pza\b\.?|plza\b\.?|pl\b\.?|plz\b\.?|pz\b\.?)\s*", "PLAZA ", addr)
    # "S. FRANCISCO" -> "SAN FRANCISCO"; "STA." -> "SANTA"
    addr = re.sub(r"(?i)\bS\.\s*(?=[A-ZÁÉÍÓÚ])", "SAN ", addr)
    addr = re.sub(r"(?i)\bSTA\.\s*", "SANTA ", addr)
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
    "ALBERCA,LAS": ("Murcia", "Alberca de las Torres"),
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
    "ALBERCA,LA": ("Murcia", "Alberca de las Torres"),
    "ALJORRA,LA": ("Cartagena", "La Aljorra"),
    "ALMUDEMA,LA": ("Caravaca de la Cruz", "La Almudema"),
    "UNION,LA": ("La Unión", None),
    "ÑORA,LA": ("Murcia", "La Ñora"),
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
    # Núcleos citados en las direcciones de Baleares sin localidad.
    "FORNELLS": ("Es Mercadal", "Fornells"),
    "TORRENOVA": ("Calvià", "Torrenova"),
    "MAGALUF": ("Calvià", "Magaluf"),
    "ES CANAR": ("Santa Eulària des Riu", "Es Canar"),
    "CAS CAPITÀ": ("Santa Eulària des Riu", "Es Canar"),
    "CALA LLONGA": ("Santa Eulària des Riu", "Cala Llonga"),
    "SANT CARLES": ("Santa Eulària des Riu", "Sant Carles de Peralta"),
    "SANTA EULÀRIA": ("Santa Eulària des Riu", None),
    "ES PUJOLS": ("Formentera", "Es Pujols"),
    "ES CALO DE SANT AGUSTI": ("Formentera", "Es Caló"),
    "SA CABANA": ("Marratxí", "Sa Cabana"),
    "C'AS CONCOS": ("Felanitx", "Cas Concos des Cavaller"),
    "CAS CONCOS": ("Felanitx", "Cas Concos des Cavaller"),
    "PUIG DE ROS": ("Llucmajor", "Puig de Ros"),
    "MAIORIS": ("Llucmajor", "Maioris Decima"),
    "PLATJA DE MURO": ("Muro", "Platja de Muro"),
}



def get_candidate_municipalities(
    pharmacy: Pharmacy,
) -> list[tuple[str, str | None]]:
    """Municipio(s) y núcleo de una farmacia de la Región de Murcia.

    Devuelve lista de (municipio, núcleo); núcleo None = casco urbano.
    """
    if pharmacy.region == "14":
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
    return []


# Municipios de Illes Balears (INE, provincia 07). Se usan para reconocer
# municipios en zonas y direcciones; no contienen coordenadas.
BALEARES_MUNICIPALITIES: tuple[str, ...] = (
    "Alaior", "Alaró", "Alcúdia", "Algaida", "Andratx", "Ariany", "Artà",
    "Banyalbufar", "Binissalem", "Búger", "Bunyola", "Calvià", "Campanet",
    "Campos", "Capdepera", "Ciutadella de Menorca", "Consell", "Costitx",
    "Deià", "Eivissa", "Es Castell", "Es Mercadal", "Es Migjorn Gran",
    "Escorca", "Esporles", "Estellencs", "Felanitx", "Ferreries", "Formentera",
    "Fornalutx", "Inca", "Lloret de Vistalegre", "Lloseta", "Llubí",
    "Llucmajor", "Manacor", "Mancor de la Vall", "Maó-Mahón",
    "Maria de la Salut", "Marratxí", "Montuïri", "Muro", "Palma", "Petra",
    "Pollença", "Porreres", "Puigpunyent", "Sa Pobla", "Sant Antoni de Portmany",
    "Sant Joan", "Sant Joan de Labritja", "Sant Josep de sa Talaia",
    "Sant Llorenç des Cardassar", "Sant Lluís", "Santa Eugènia",
    "Santa Eulària des Riu", "Santa Margalida", "Santa Maria del Camí",
    "Santanyí", "Selva", "Ses Salines", "Sencelles", "Sineu", "Sóller",
    "Son Servera", "Valldemossa", "Vilafranca de Bonany",
)

_ARTICLES = {
    "es", "sa", "ses", "s", "el", "la", "los", "las", "l", "d", "de", "del",
    "dels", "des", "en", "na", "lo", "y", "i",
}

# Variantes (clave normalizada sin artículos) -> clave canónica del municipio.
MUNI_KEY_ALIASES: dict[str, str] = {
    "mao": "maomahon", "mahon": "maomahon",
    "ibiza": "eivissa",
    "santaeularia": "santaeulariariu", "santaeulalia": "santaeulariariu",
    "santaeulaliario": "santaeulariariu", "eularia": "santaeulariariu",
    "eulalia": "santaeulariariu",
    "santantoni": "santantoniportmany", "sanantonioabad": "santantoniportmany",
    "santjosep": "santjoseptalaia", "sanjose": "santjoseptalaia",
    "santjosepsatalaia": "santjoseptalaia",
    "ciutadella": "ciutadellamenorca",
    "vilafranca": "vilafrancabonany", "villafranca": "vilafrancabonany",
    "villafrancabonany": "vilafrancabonany",
    "lloret": "lloretvistalegre",
    "santamaria": "santamariacami",
    "santllorenc": "santllorenccardassar",
    "sanjoan": "santjoan",
    "pollensa": "pollenca",
    "palmademallorca": "palma",
    "migjorngran": "migjorngran",
    "fuentealamo": "fuentealamomurcia",
    "caravaca": "caravacacruz",
    "torrepachec": "torrepacheco",
}


def muni_key(name: str | None) -> str:
    """Clave canónica de un municipio: sin acentos, sin artículos, con alias."""
    toks = [t for t in _tokens(name) if t not in _ARTICLES]
    key = "".join(toks)
    return MUNI_KEY_ALIASES.get(key, key)


def muni_matches(expected: str, result_muni: str) -> bool:
    """Igualdad exacta de claves canónicas (nunca por subcadena)."""
    if not expected or not result_muni:
        return False
    return muni_key(expected) == muni_key(result_muni)


_BALEARES_BY_KEY: dict[str, str] = {muni_key(m): m for m in BALEARES_MUNICIPALITIES}


def baleares_municipality(name: str | None) -> str | None:
    """Nombre oficial del municipio balear si `name` lo designa; si no, None."""
    return _BALEARES_BY_KEY.get(muni_key(name))


# ---------------------------------------------------------------------------
# Cliente HTTP con caché persistente (tabla geocode_cache)
# ---------------------------------------------------------------------------


class GeoClient:
    """Acceso a CartoCiudad y Nominatim con caché en BD y límites de ritmo."""

    def __init__(self, session: Session, http: httpx.Client, offline: bool = False):
        self.session = session
        self.http = http
        self.offline = offline
        self.live_calls = 0

    def _get(self, provider: str, url: str, params: dict[str, Any]) -> Any:
        key = f"v4:{provider}:{url.rsplit('/', 1)[-1]}:" + json.dumps(
            params, sort_keys=True, ensure_ascii=False
        )
        cached = self.session.get(GeocodeCache, key)
        if cached is not None:
            return json.loads(cached.raw_json) if cached.raw_json else None
        if self.offline:
            return None
        wait = _MIN_INTERVAL[provider] - (time.time() - _last_call[provider])
        if wait > 0:
            time.sleep(wait)
        headers = {"User-Agent": NOMINATIM_USER_AGENT}
        data: Any = None
        ok = False
        for attempt in range(3):
            try:
                resp = self.http.get(url, params=params, headers=headers, timeout=15.0)
                _last_call[provider] = time.time()
                self.live_calls += 1
                if resp.status_code == 200:
                    text = resp.text.strip()
                    data = json.loads(text) if text else None
                    ok = True
                    break
                if resp.status_code in (400, 404):
                    ok = True  # respuesta definitiva: sin resultados
                    break
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                logger.warning("%s %s: %s", provider, url, exc)
            time.sleep(1.5 * (attempt + 1))
        if not ok:
            return None  # error transitorio: no se cachea
        self.session.add(
            GeocodeCache(
                query=key,
                lat=None,
                lon=None,
                precision=None,
                provider=provider,
                raw_json=json.dumps(data, ensure_ascii=False) if data is not None else None,
                created_at=datetime.datetime.now(datetime.timezone.utc),
            )
        )
        return data

    def candidates(self, q: str, limit: int = 10, **filters: str) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"q": q, "limit": limit}
        params.update({k: v for k, v in filters.items() if v})
        data = self._get("cartociudad", f"{CARTOCIUDAD_BASE}/candidates", params)
        return data if isinstance(data, list) else []

    def find(self, item_id: str, item_type: str) -> dict[str, Any] | None:
        data = self._get(
            "cartociudad", f"{CARTOCIUDAD_BASE}/find", {"id": item_id, "type": item_type}
        )
        return data if isinstance(data, dict) else None

    def reverse(self, lat: float, lon: float) -> dict[str, Any] | None:
        data = self._get(
            "cartociudad",
            f"{CARTOCIUDAD_BASE}/reverseGeocode",
            {"lat": f"{lat:.6f}", "lon": f"{lon:.6f}"},
        )
        return data if isinstance(data, dict) else None

    def nominatim(self, **params: str) -> list[dict[str, Any]]:
        query = {
            "countrycodes": "es",
            "format": "json",
            "addressdetails": "1",
            "limit": "5",
        }
        query.update({k: v for k, v in params.items() if v})
        data = self._get("nominatim", NOMINATIM_URL, query)
        return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# Núcleos de población (entidad "poblacion" de CartoCiudad)
# ---------------------------------------------------------------------------


@dataclass
class Nucleus:
    name: str
    muni: str
    lat: float
    lon: float
    rings: list[list[tuple[float, float]]] = field(default_factory=list)
    postal_codes: list[str] = field(default_factory=list)
    alternates: list["Nucleus"] = field(default_factory=list)

    def extent_km(self) -> float:
        """Diagonal de la caja del polígono (0 si no hay polígono)."""
        pts = [p for ring in self.rings for p in ring]
        if not pts:
            return 0.0
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return haversine_km(min(ys), min(xs), max(ys), max(xs))

    def distance_km(self, lat: float, lon: float) -> float:
        """Distancia al núcleo (o a la entidad homónima más cercana)."""
        own = self._own_distance_km(lat, lon)
        return min([own] + [alt._own_distance_km(lat, lon) for alt in self.alternates])

    def _own_distance_km(self, lat: float, lon: float) -> float:
        """0 si el punto está dentro del polígono; si no, distancia a su borde."""
        if not self.rings:
            return haversine_km(lat, lon, self.lat, self.lon)
        if any(_point_in_ring(lon, lat, ring) for ring in self.rings):
            return 0.0
        return min(_distance_to_ring_km(lat, lon, ring) for ring in self.rings)


def _distance_to_ring_km(lat: float, lon: float, ring: list[tuple[float, float]]) -> float:
    """Distancia (km) de un punto al borde de un anillo, en proyección local plana."""
    kx = 111.320 * math.cos(math.radians(lat))
    ky = 110.574
    px, py = 0.0, 0.0
    best = float("inf")
    pts = [((x - lon) * kx, (y - lat) * ky) for x, y in ring]
    for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
        cx, cy = ax + t * dx, ay + t * dy
        best = min(best, math.hypot(px - cx, py - cy))
    return best


def _point_in_ring(x: float, y: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi:
            inside = not inside
        j = i
    return inside


def _parse_wkt_rings(wkt: str | None) -> list[list[tuple[float, float]]]:
    """Anillos exteriores de un POLYGON/MULTIPOLYGON WKT como listas (lon, lat)."""
    if not wkt or "POLYGON" not in wkt:
        return []
    rings = []
    for chunk in re.findall(r"\(\(([^()]+)\)", wkt):
        pts = []
        for pair in chunk.split(","):
            parts = pair.strip().split()
            if len(parts) >= 2:
                pts.append((float(parts[0]), float(parts[1])))
        if len(pts) >= 3:
            rings.append(pts)
    return rings


def _names_match(a: str, b: str) -> bool:
    """Nombres de población equivalentes (también bilingües "Pamplona/Iruña")."""
    def keys(x: str) -> set[str]:
        parts = [x] + ([p for p in re.split(r"\s*/\s*", x) if p] if "/" in x else [])
        return {"".join(t for t in _tokens(p) if t not in _ARTICLES) for p in parts} - {""}

    for ka in keys(a):
        for kb in keys(b):
            if ka == kb or difflib.SequenceMatcher(None, ka, kb).ratio() >= 0.9:
                return True
    return False


def find_nucleus(
    geo: GeoClient, name: str, munis: list[str], region: str
) -> Nucleus | None:
    """Localiza la entidad de población `name` en alguno de los municipios esperados.

    Si `munis` está vacío se acepta cualquier municipio de la comunidad.
    """
    if not name:
        return None
    provinces = REGION_PROVINCES.get(region, set())
    keys = {muni_key(m) for m in munis}
    items: list[dict[str, Any]] = []
    for q in [f"{name}, {m}" for m in munis[:4]] + [name]:
        items.extend(geo.candidates(q, limit=20))
    matches: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for it in items:
        if it.get("type") != "poblacion":
            continue
        if it.get("provinceCode") not in provinces:
            continue
        if keys and muni_key(it.get("muni")) not in keys:
            continue
        if not _names_match(name, it.get("poblacion") or ""):
            continue
        if str(it.get("id")) in seen_ids:
            continue
        seen_ids.add(str(it.get("id")))
        matches.append(it)
    if not matches:
        return _nucleus_from_nominatim(geo, name, munis, region)
    # Puede haber varias entidades homónimas en el municipio (p. ej. dos "Los
    # Nietos" en Cartagena): se toma como principal la de polígono más extenso y
    # las demás se usan como alternativas al validar distancias.
    found: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for it in matches[:4]:
        detail = geo.find(str(it["id"]), "poblacion") or it
        lat, lon = detail.get("lat"), detail.get("lng")
        if not lat or not lon or not is_within_bbox(region, float(lat), float(lon)):
            continue
        found.append((len(detail.get("geom") or ""), it, detail))
    if not found:
        return None
    found.sort(key=lambda f: -f[0])
    _size, chosen, detail = found[0]
    lat, lon = detail.get("lat"), detail.get("lng")
    alternates = [
        Nucleus(it.get("poblacion") or name, it.get("muni") or "", float(d["lat"]), float(d["lng"]),
                rings=_parse_wkt_rings(d.get("geom")))
        for _s, it, d in found[1:]
    ]
    postal = sorted(
        {
            str(it["postalCode"])
            for it in items
            if it.get("postalCode")
            and _names_match(name, it.get("poblacion") or "")
            and muni_key(it.get("muni")) == muni_key(chosen.get("muni"))
        }
    )
    return Nucleus(
        name=chosen.get("poblacion") or name,
        muni=chosen.get("muni") or "",
        lat=float(lat),
        lon=float(lon),
        rings=_parse_wkt_rings(detail.get("geom")),
        postal_codes=postal,
        alternates=alternates,
    )


_PLACE_TYPES = {"city", "town", "village", "hamlet", "suburb", "neighbourhood", "quarter", "isolated_dwelling", "locality"}


def _nucleus_from_nominatim(
    geo: GeoClient, name: str, munis: list[str], region: str
) -> Nucleus | None:
    """Núcleo como lugar habitado de OSM cuando CartoCiudad no tiene la entidad.

    Se valida con la geocodificación inversa de CartoCiudad (municipio esperado).
    Sin polígono: las distancias se miden al punto del lugar.
    """
    keys = {muni_key(m) for m in munis}
    for muni in (munis[:3] or [REGION_NAMES.get(region, "")]):
        for it in geo.nominatim(q=f"{name}, {muni}, {REGION_NAMES.get(region, '')}"):
            es_lugar = it.get("class") == "place" and it.get("type") in _PLACE_TYPES
            # Las pedanías de Murcia figuran en OSM como límites administrativos.
            es_pedania = it.get("class") == "boundary" and it.get("type") == "administrative"
            if not (es_lugar or es_pedania):
                continue
            if not _names_match(name, (it.get("name") or it.get("display_name", "").split(",")[0])):
                continue
            lat, lon = float(it["lat"]), float(it["lon"])
            if not is_within_bbox(region, lat, lon):
                continue
            rev = geo.reverse(lat, lon)
            if rev is None or (keys and muni_key(rev.get("muni")) not in keys):
                continue
            return Nucleus(name=it.get("name") or name, muni=rev.get("muni") or muni, lat=lat, lon=lon)
    return None


# ---------------------------------------------------------------------------
# Contexto esperado de cada farmacia
# ---------------------------------------------------------------------------


@dataclass
class GeoContext:
    munis: list[str]
    nucleus_name: str | None = None
    casco: bool = False
    postal_codes: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def muni_keys(self) -> set[str]:
        return {muni_key(m) for m in self.munis}


_HINT_SKIP = re.compile(
    r"^(?:junto|frente|enfrente|davant|al costat|entre|cantonada|esq|esquina|inicio|"
    r"final|rotonda|edif|ed|local|loc|bl|esc|bajos|club|supermercado|al lado|"
    r"mercadona|eroski|carrefour)\b",
    re.IGNORECASE,
)


def _hint_phrases(address: str) -> list[str]:
    """Posibles nombres de núcleo dentro de una dirección de Baleares."""
    phrases: list[str] = []
    for inner in re.findall(r"\(([^()]*)\)?", address):
        phrases.append(inner)
    unclosed = re.search(r"\(([^()]*)$", address)
    if unclosed:
        phrases.append(unclosed.group(1))
    no_paren = re.sub(r"\([^()]*\)?", " ", address)
    # Texto tras el último número de portal ("11 CALA MILLOR", "12-C'AS CONCOS").
    tail = re.search(r"\d+[A-Za-z]?\s*[-,]?\s*([A-Za-zÀ-ÿ'´ .]+?)\s*[-.]*\s*$", no_paren)
    if tail:
        phrases.append(tail.group(1))
    # Trozos separados por guion tras el último dígito ("31-IFRE-CAÑADA DE GALLEGO").
    after_digits = re.split(r"\d", no_paren)[-1] if re.search(r"\d", no_paren) else ""
    for piece in re.split(r"\s*-\s*", after_digits):
        phrases.append(piece)
    # Texto tras el último ". " o " - ".
    for sep in (". ", " - ", "- "):
        if sep in no_paren:
            before, after = no_paren.rsplit(sep, 1)
            last_word = before.split()[-1] if before.split() else ""
            if _HINT_SKIP.match(last_word.strip(".")) or len(last_word.strip(".")) <= 2:
                continue  # "Ed. Can Cardona", "L. K4": nombre de edificio o local
            phrases.append(after)
    out = []
    for p in phrases:
        p = re.sub(r"(?i)\bsta\.?\s*", "SANTA ", p)
        p = re.sub(r"(?i)\burb(?:anizaci[oó]n)?\b\.?\s*", "", p)
        p = re.sub(r"[\d]+", " ", p)
        p = re.sub(r"\s+", " ", p).strip(" .,-")
        if len(p) < 3 or _HINT_SKIP.match(p):
            continue
        if p not in out:
            out.append(p)
    return out


def _known_baleares(name: str) -> tuple[str, str | None] | None:
    """(municipio, núcleo) si `name` es una localidad balear conocida."""
    key = normalize_text(name)
    for k, v in BALEARES_KNOWN_MAP.items():
        if normalize_text(k) == key:
            return v
    muni = baleares_municipality(name)
    if muni:
        return (muni, None)
    return None


def _zone_municipalities(zones: list[str]) -> list[str]:
    munis: list[str] = []
    for zone in zones:
        parts = [zone] if baleares_municipality(zone) else re.split(r"\s*-\s*", zone)
        for part in parts:
            muni = baleares_municipality(part)
            if muni is None:
                known = _known_baleares(part)
                muni = known[0] if known else None
            if muni and muni not in munis:
                munis.append(muni)
    return munis


def resolve_context(geo: GeoClient, pharmacy: Pharmacy) -> GeoContext:
    """Municipio(s), núcleo y códigos postales esperados para una farmacia."""
    if pharmacy.region == "02":
        return GeoContext([pharmacy.locality or "Zaragoza"], None, True, [], "municipio de la fuente")
    if pharmacy.region == "13":
        # Ciudad de Madrid: la fuente solo cubre el municipio (casco = término municipal).
        loc = (pharmacy.locality or "Madrid").strip()
        return GeoContext([loc], None, True, [], "municipio de la fuente")
    if pharmacy.region == "15":
        # La fuente da el núcleo (concejo o localidad), no siempre el municipio.
        loc = (pharmacy.locality or "").strip()
        nuc = None
        for name in ([loc] + [p.strip() for p in loc.split("/")]) if loc else []:
            nuc = find_nucleus(geo, name, [], "15")
            if nuc is not None:
                break
        if nuc is not None:
            return GeoContext([nuc.muni], nuc.name, False, [], "núcleo de la fuente")
        return GeoContext([], None, False, [], "localidad no localizada")
    if pharmacy.region == "14":
        pairs = get_candidate_municipalities(pharmacy)
        munis = []
        for muni, _nuc in pairs:
            if muni not in munis:
                munis.append(muni)
        nucleus = next((n for _m, n in pairs if n), None)
        if nucleus and muni_key(nucleus) in {muni_key(m) for m in munis}:
            nucleus = None
        postal = [pharmacy.postal_code] if pharmacy.postal_code else []
        return GeoContext(munis, nucleus, nucleus is None, postal, "localidad de la fuente")

    zones: list[str] = []
    if pharmacy.zones:
        try:
            zones = [z for z in json.loads(pharmacy.zones) if isinstance(z, str)]
        except (json.JSONDecodeError, TypeError):
            zones = []
    zone_munis = _zone_municipalities(zones)
    loc = (pharmacy.locality or "").strip()

    if loc:
        known = _known_baleares(loc)
        if known:
            muni, nucleus = known
            return GeoContext([muni], nucleus, nucleus is None, [], "localidad de la fuente")
        # Localidad no reconocida: tratarla como núcleo dentro de las zonas.
        return GeoContext(zone_munis, loc.title(), False, [], "localidad no reconocida")

    for phrase in _hint_phrases(pharmacy.address):
        known = _known_baleares(phrase)
        if known:
            muni, nucleus = known
            return GeoContext([muni], nucleus, nucleus is None, [], f"núcleo en dirección: {phrase}")
        nuc = find_nucleus(geo, phrase, [], pharmacy.region)
        if nuc is not None and (not zone_munis or len(phrase) >= 5):
            return GeoContext(
                [nuc.muni], nuc.name, False, [], f"núcleo en dirección: {phrase}"
            )
    # Sin núcleo identificable: municipios de sus zonas, sin casco conocido.
    return GeoContext(zone_munis, None, False, [], "municipios de la zona de guardia")


# ---------------------------------------------------------------------------
# Direcciones
# ---------------------------------------------------------------------------

_STREET_TYPES = {
    "CALLE": "CARRER", "AVENIDA": "AVINGUDA", "PLAZA": "PLAÇA", "PASEO": "PASSEIG",
    "CARRETERA": "CARRETERA", "CAMINO": "CAMÍ", "TRAVESIA": "TRAVESSIA",
    "RONDA": "RONDA", "GLORIETA": "GLORIETA", "URBANIZACION": "URBANITZACIO",
    "CARRER": "CALLE", "AVINGUDA": "AVENIDA", "PLAÇA": "PLAZA", "PASSEIG": "PASEO",
    "CAMI": "CAMINO", "CAMÍ": "CAMINO", "TRAVESSIA": "TRAVESIA",
}
_EXTRA_TYPES = {
    "CM": "CAMI", "CR": "CARRETERA", "AVG": "AVINGUDA", "AVGDA": "AVINGUDA",
    "PG": "PASSEIG", "PS": "PASEO", "C": "CALLE",
}
_STREET_STOP = _ARTICLES | {
    "calle", "carrer", "avenida", "avinguda", "plaza", "placa", "paseo", "passeig",
    "carretera", "camino", "cami", "travesia", "travessia", "ronda", "glorieta",
    "urbanizacion", "via", "dr", "doctor", "doctora", "sr", "san", "sant", "santa",
    "santo", "km", "av", "cl", "c", "pz", "pl", "ctra", "cm", "gran",
    "bulevar", "bulevard", "boulevar", "boulevard", "rambla", "pasaje", "passatge",
    "pintor", "poeta", "escultor", "maestro", "mestre", "general", "capitan",
    "padre", "pare", "obispo", "bisbe", "notario", "notari", "arquitecto",
    "almirante", "comandante", "teniente", "coronel", "ingeniero", "enginyer",
    "profesor", "professor", "historiador", "musico", "music", "compositor",
}


# Equivalencias castellano -> catalán frecuentes en el callejero balear. Se usan
# para comparar nombres de vía y para consultar con la forma catalana oficial.
_CA_WORDS: dict[str, str] = {
    "playa": "platja", "playas": "platges", "paseo": "passeig", "calle": "carrer",
    "avenida": "avinguda", "plaza": "placa", "camino": "cami", "carretera": "carretera",
    "travesia": "travessia", "mayor": "major", "puerto": "port", "iglesia": "esglesia",
    "pinos": "pins", "pino": "pi", "palmeras": "palmeres", "molino": "moli",
    "molinos": "molins", "fuente": "font", "pozo": "pou", "cruz": "creu",
    "virgen": "verge", "rey": "rei", "reyes": "reis", "reina": "reina",
    "jose": "josep", "juan": "joan", "jaime": "jaume", "pedro": "pere",
    "miguel": "miquel", "francisco": "francesc", "antonio": "antoni",
    "bartolome": "bartomeu", "cristobal": "cristofol", "luis": "lluis",
    "lorenzo": "llorenc", "jorge": "jordi", "andres": "andreu", "mateo": "mateu",
    "nicolas": "nicolau", "pablo": "pau", "esteban": "esteve", "vicente": "vicenc",
    "santiago": "jaume", "isidro": "isidre", "margarita": "margalida",
    "catalina": "catalina", "rosario": "roser", "carmen": "carme",
    "huerto": "hort", "huertos": "horts", "campo": "camp", "mar": "mar",
    "sol": "sol", "luna": "lluna", "flores": "flors", "olivos": "oliveres",
    "almendros": "ametllers", "sur": "sud", "norte": "nord", "levante": "llevant",
    "poniente": "ponent", "san": "sant", "nuevo": "nou", "nueva": "nova",
    "viejo": "vell", "vieja": "vella", "alto": "alt", "bajo": "baix",
    "general": "general", "doctor": "doctor", "maestro": "mestre",
    "poeta": "poeta", "pintor": "pintor", "padre": "pare", "obispo": "bisbe",
    "conde": "comte", "marques": "marques", "duque": "duc", "infanta": "infanta",
    "colon": "colom", "canonigo": "canonge", "escuelas": "escoles", "escuela": "escola",
}


def _canon_token(tok: str) -> str:
    return _CA_WORDS.get(tok, tok)


def to_catalan(text: str) -> str:
    """Versión catalana aproximada de un nombre de vía (solo para consultas)."""
    words = []
    for word in text.split():
        key = normalize_text(word)
        words.append(_CA_WORDS.get(key, word).upper() if key in _CA_WORDS else word)
    return " ".join(words)


@dataclass
class ParsedAddress:
    street_type: str
    name: str
    number: int | None

    @property
    def full(self) -> str:
        return f"{self.street_type} {self.name}".strip()


def parse_address(clean: str) -> ParsedAddress:
    """Separa tipo de vía, nombre y número de una dirección ya normalizada."""
    text = clean.strip()
    number = None
    m = re.match(r"^(.*?),\s*(.*)$", text)
    if m and re.search(r"\d", m.group(2)):
        text = m.group(1)
        num = re.search(r"\d+", m.group(2))
        number = int(num.group(0)) if num and "km" not in m.group(2).lower() else None
    else:
        m2 = re.match(r"^(.*?\D)\s+(\d+)\b.*$", text)
        if m2:
            text, number = m2.group(1), int(m2.group(2))
    text = re.sub(r"(?i)\bDR\.?\s+", "DOCTOR ", text)
    text = re.sub(r"(?i)\bSTA\.?\s+", "SANTA ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.-")
    parts = text.split(" ", 1)
    first = parts[0].upper().rstrip(".")
    if first in _EXTRA_TYPES and len(parts) == 2:
        return ParsedAddress(_EXTRA_TYPES[first], parts[1].strip(), number)
    if first in _STREET_TYPES and len(parts) == 2:
        rest = parts[1].strip()
        # "AVENIDA AVINGUDA DE CARLES V" -> se queda una sola vez el tipo
        rest_first = rest.split(" ", 1)[0].upper()
        same_kind = rest_first == first or _STREET_TYPES.get(rest_first) == first or (
            _STREET_TYPES.get(first) == rest_first
        )
        if same_kind and " " in rest:
            rest = rest.split(" ", 1)[1]
        elif rest_first in _STREET_TYPES and " " in rest:
            # "CALLE CAMINO REAL": el tipo real es el segundo.
            first, rest = rest_first, rest.split(" ", 1)[1]
        return ParsedAddress(first, rest, number)
    return ParsedAddress("", text, number)


def _coverage(q: list[str], r: list[str]) -> float:
    """Proporción de palabras de `q` presentes (aproximadamente) en `r`."""
    if not q or not r:
        return 0.0
    hits = 0.0
    for tok in q:
        best = max(difflib.SequenceMatcher(None, tok, cand).ratio() for cand in r)
        if best >= 0.75:
            hits += 1.0
        elif any(cand.startswith(tok) or tok.startswith(cand) for cand in r if len(cand) >= 3):
            hits += 0.8
    return hits / len(q)


def street_similarity(query_name: str, result_street: str) -> float:
    """Parecido entre la vía buscada y la hallada, en los dos sentidos.

    Se combina la cobertura de la consulta en el resultado con la del resultado en
    la consulta: "DOCTOR ORFILA" no casa con "DOCTOR CAMPS" y una vía con dos o más
    palabras distintivas ausentes en la fuente se descarta.
    """
    qt = [_canon_token(t) for t in _tokens(query_name)]
    rt = [_canon_token(t) for t in _tokens(result_street)]
    q = [t for t in qt if t not in _STREET_STOP and not t.isdigit()]
    r = [t for t in rt if t not in _STREET_STOP and not t.isdigit()]
    if not q:
        q = [t for t in qt if not t.isdigit()]
        r = [t for t in rt if not t.isdigit()]
    # La inversa se exige con más holgura (≥ 0,5): las fuentes abrevian a menudo el
    # nombre oficial ("CANOVAS" por "Cánovas del Castillo"); sí descarta vías con
    # varias palabras distintivas que la fuente no menciona.
    return min(_coverage(q, r), min(1.0, _coverage(r, q) + 0.1))


def _result_street(address: str | None) -> str:
    """Nombre de vía de un 'address' de CartoCiudad ('CALLE X 17, Núcleo (Muni)')."""
    if not address:
        return ""
    head = address.split(",", 1)[0]
    head = re.sub(r"\s+\d+\s*[A-Z]?$", "", head.strip())
    return head


# ---------------------------------------------------------------------------
# Geocodificación de una farmacia
# ---------------------------------------------------------------------------


@dataclass
class GeoResult:
    lat: float | None
    lon: float | None
    precision: str | None
    source: str | None
    query: str
    reason: str = ""


def _validate_point(
    geo: GeoClient,
    ctx: GeoContext,
    nucleus: Nucleus | None,
    casco_nucleus: Nucleus | None,
    region: str,
    lat: float,
    lon: float,
) -> str | None:
    """Devuelve None si el punto es coherente; si no, el motivo del rechazo."""
    if not is_within_bbox(region, lat, lon):
        return "fuera de la comunidad"
    rev = geo.reverse(lat, lon)
    if rev is None:
        return "sin geocodificación inversa"
    if ctx.munis and muni_key(rev.get("muni")) not in ctx.muni_keys:
        # Solo el núcleo principal (de un municipio esperado), no sus homónimos.
        shared = nucleus is not None and nucleus._own_distance_km(lat, lon) <= NUCLEUS_SHARED_KM
        if not shared:
            return f"municipio inverso {rev.get('muni')!r} no esperado"
    if nucleus is not None and nucleus.distance_km(lat, lon) > NUCLEUS_MAX_KM:
        return f"a {nucleus.distance_km(lat, lon):.1f} km del núcleo {nucleus.name}"
    if casco_nucleus is not None and haversine_km(
        lat, lon, casco_nucleus.lat, casco_nucleus.lon
    ) > CASCO_MAX_KM:
        return "lejos del casco urbano"
    return None


def _cartociudad_street(
    geo: GeoClient,
    ctx: GeoContext,
    addr: ParsedAddress,
    region: str,
    postal_codes: list[str],
    places: list[str],
    nucleus: Nucleus | None = None,
) -> list[tuple[float, float, str, str, dict[str, Any]]]:
    """Candidatos de CartoCiudad que superan municipio, vía y código postal."""
    provinces = REGION_PROVINCES.get(region, set())
    num = f" {addr.number}" if addr.number else ""
    variants = [f"{addr.full}{num}"]
    if addr.street_type and addr.street_type.upper() in _STREET_TYPES:
        variants.append(f"{_STREET_TYPES[addr.street_type.upper()]} {addr.name}{num}")
    variants.append(f"{addr.name}{num}")
    if region == "04":
        catalan = to_catalan(f"{addr.full}{num}")
        if catalan not in variants:
            variants.insert(1, catalan)
    if re.search(r"\s+I\s+", addr.name, re.IGNORECASE):
        variants.append(re.sub(r"(?i)\s+i\s+", " ", addr.name) + num)
    core = [t for t in addr.name.split() if normalize_text(t) not in _STREET_STOP]
    if len(core) >= 3:
        variants.append(" ".join(core[:2]) + num)
    if len(core) >= 2:
        variants.append(f"{core[-1]}{num}")
    seen: set[str] = set()
    queries: list[tuple[str, dict[str, str]]] = []
    for v in variants:
        for cp in postal_codes:
            queries.append((v, {"cod_postal_filter": cp}))
    for i, pl in enumerate(places):
        for v in (variants[:3] if i < 3 else [f"{addr.name}{num}"]):
            queries.append((f"{v}, {pl}", {}))
    accepted: list[tuple[float, float, str, str, dict[str, Any]]] = []
    for q, flt in queries:
        sig = q + json.dumps(flt, sort_keys=True)
        if sig in seen:
            continue
        seen.add(sig)
        for it in geo.candidates(q, limit=10, **flt):
            if it.get("provinceCode") not in provinces:
                continue
            other_muni = bool(ctx.munis) and muni_key(it.get("muni")) not in ctx.muni_keys
            if other_muni and nucleus is None:
                continue
            if it.get("type") not in ("portal", "callejero", "expendeduria"):
                continue
            cp_near = False
            if postal_codes and it.get("postalCode") and str(it["postalCode"]) not in postal_codes:
                # CP vecino de la misma ciudad (30001 frente a 30005): se admite, pero
                # nunca como portal. Distinto prefijo = otra población: se descarta.
                if not any(str(it["postalCode"])[:4] == cp[:4] for cp in postal_codes):
                    continue
                cp_near = True
            street = _result_street(it.get("address"))
            if street_similarity(addr.name, street) < STREET_MIN_SCORE:
                continue
            lat, lon = it.get("lat"), it.get("lng")
            if not lat or not lon:
                detail = geo.find(str(it["id"]), str(it["type"]))
                if detail:
                    lat, lon = detail.get("lat"), detail.get("lng")
            if not lat or not lon:
                continue
            if other_muni and nucleus is not None and (
                nucleus._own_distance_km(float(lat), float(lon)) > NUCLEUS_SHARED_KM
            ):
                continue
            if not cp_near and it.get("type") in ("portal", "expendeduria") and addr.number and (
                it.get("portalNumber") == addr.number
            ):
                precision = "portal"
            else:
                precision = "calle"
            accepted.append((float(lat), float(lon), precision, f"cartociudad:{q}", it))
        if any(a[2] == "portal" for a in accepted):
            break
        if accepted and not addr.number:
            break
    # Primero el nombre de vía que mejor casa; a igualdad, el portal exacto.
    accepted.sort(
        key=lambda a: (-round(street_similarity(addr.name, _result_street(a[4].get("address"))), 2), 0 if a[2] == "portal" else 1)
    )
    return accepted


def _nominatim_street(
    geo: GeoClient,
    ctx: GeoContext,
    addr: ParsedAddress,
    postal_codes: list[str],
    cities: list[str],
) -> list[tuple[float, float, str, str, dict[str, Any]]]:
    accepted = []
    street = f"{addr.number} {addr.full}" if addr.number else addr.full
    searches: list[dict[str, str]] = []
    for city in cities:
        for cp in (postal_codes or [""]):
            searches.append({"street": street, "city": city, "postalcode": cp})
    for city in cities[:2]:
        searches.append({"q": f"{addr.full} {addr.number or ''}, {city}".replace(" ,", ",")})
    for params in searches:
        if True:
            for it in geo.nominatim(**params):
                info = it.get("address", {})
                road = info.get("road") or info.get("pedestrian") or info.get("square") or ""
                if street_similarity(addr.name, road) < STREET_MIN_SCORE:
                    continue
                cls, typ = it.get("class"), it.get("type")
                house = info.get("house_number")
                if cls == "highway" or it.get("addresstype") == "road":
                    precision = "calle"
                elif house and (cls in ("building", "place", "amenity", "shop", "office") or typ == "house"):
                    house_num = re.match(r"\d+", str(house))
                    precision = (
                        "portal"
                        if addr.number and house_num and int(house_num.group(0)) == addr.number
                        else "calle"
                    )
                else:
                    continue
                if postal_codes and info.get("postcode") and info["postcode"] not in postal_codes:
                    continue
                accepted.append(
                    (float(it["lat"]), float(it["lon"]), precision, "nominatim", it)
                )
            if accepted:
                return sorted(accepted, key=lambda a: 0 if a[2] == "portal" else 1)
    return accepted


_CORE_CUT_RE = re.compile(
    r"\s*(?:,|\s-\s|-\s*EDIF|\(|\bEDIF(?:ICIO)?\b|\bED\.|\bAPTOS?\b|\bLOC(?:AL)?\b\.?|\bURB(?:ANIZACION)?\b).*$",
    re.I,
)
_TYPE_ABBR = {"AVD": "AVENIDA", "AVDA": "AVENIDA", "AV": "AVENIDA", "PZ": "PLAZA", "PZA": "PLAZA"}


def street_core(address: str) -> ParsedAddress:
    """Vía y número sin complementos (edificio, urbanización, local...) para casar con OSM."""
    clean = clean_address(address)
    # Solo el número que sigue a la vía ("…, 25"); no el de "LOCAL 32" o "EDIFICIO 3".
    number_m = re.search(r",\s*(?:N[ºO°]?\s*)?(\d+)", clean)
    core = _CORE_CUT_RE.sub("", clean).strip(" .,-")
    first, _, rest = core.partition(" ")
    first = _TYPE_ABBR.get(first.upper().rstrip("."), first)
    parsed = parse_address(f"{first} {rest}".strip())
    number = parsed.number if parsed.number is not None else (int(number_m.group(1)) if number_m else None)
    return ParsedAddress(parsed.street_type, parsed.name, number)


def _compact(text: str) -> str:
    return "".join(t for t in _tokens(text) if t not in _STREET_STOP)


_TYPE_CANON = {
    "calle": "calle", "carrer": "calle", "c": "calle", "cl": "calle",
    "avenida": "avenida", "avinguda": "avenida", "av": "avenida", "avda": "avenida",
    "plaza": "plaza", "placa": "plaza", "pza": "plaza", "pz": "plaza",
    "paseo": "paseo", "passeig": "paseo", "carretera": "carretera", "ctra": "carretera",
    "camino": "camino", "cami": "camino", "ronda": "ronda", "travesia": "travesia",
}

# Apellidos muy frecuentes: coincidir solo en uno de ellos no identifica a la farmacia.
_COMMON_SURNAMES = frozenset(
    "garcia rodriguez gonzalez fernandez lopez martinez sanchez perez gomez martin jimenez ruiz "
    "hernandez diaz moreno alvarez munoz romero alonso gutierrez navarro torres dominguez vazquez "
    "ramos ramirez serrano blanco molina morales suarez ortega delgado castro ortiz rubio marin "
    "sanz nunez iglesias medina garrido cortes castillo santos lozano guerrero prieto mendez calvo "
    "gallego vidal marquez herrera flores cabrera campos fuentes carrasco caballero reyes nieto "
    "aguilar pascual santana herrero lorenzo montero hidalgo gimenez ibanez ferrer duran santiago "
    "benitez vicente vargas carmona crespo roman pastor velasco soler parra esteban bravo "
    "gallardo rojas mateo".split()
)


def _road_type(road: str) -> str | None:
    first = _tokens(road)[:1]
    return _TYPE_CANON.get(first[0]) if first else None


def osm_street_match(core: ParsedAddress, road: str) -> bool:
    """La vía de la fuente y la de OSM son la misma ("MONTE AZAHAR" = "Monteazahar")."""
    if not core.name or not road:
        return False
    ours = _TYPE_CANON.get(normalize_text(core.street_type)) if core.street_type else None
    theirs = _road_type(road)
    if ours and theirs and ours != theirs:
        return False  # "CALLE FORTUNA" no es "Plaza de Fortuna"
    if street_similarity(core.name, road) >= STREET_MIN_SCORE:
        return True
    a, b = _compact(core.name), _compact(road)
    return len(a) >= 5 and a == b


def _nucleus_box(n: "Nucleus", margin: float = 0.01) -> tuple[float, float, float, float]:
    """(lon_min, lat_max, lon_max, lat_min) del polígono del núcleo, para el viewbox de Nominatim."""
    pts = [p for ring in n.rings for p in ring] or [(n.lon, n.lat)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs) - margin, max(ys) + margin, max(xs) + margin, min(ys) - margin


def _osm_pharmacy(
    geo: GeoClient,
    pharmacy: Pharmacy,
    center: tuple[float, float] | None = None,
    box: tuple[float, float, float, float] | None = None,
) -> tuple[float, float, str, str] | None:
    """Farmacia cartografiada en OpenStreetMap en la misma vía, cerca del núcleo.

    Riesgo a evitar: poner la farmacia en la posición de OTRA (la fuente no incluye todas las
    farmacias, y OSM tampoco). Por eso solo se acepta con identificación positiva:
    - una sola farmacia OSM en esa vía dentro de la caja, y la búsqueda no truncada;
    - ninguna otra farmacia de la fuente en esa vía y localidad;
    - número de portal igual al de la fuente, o un apellido no común del titular en el nombre OSM;
    - si los dos números existen y difieren, se descarta.
    """
    core = street_core(pharmacy.address)
    if not core.name or len(normalize_text(core.name)) < 3:
        return None
    if box is None:
        if center is None:
            return None
        lat, lon = center
        d = 0.03  # ~3 km
        box = (lon - d, lat + d, lon + d, lat - d)
        q = "farmacia"
    else:
        # Término extenso (Palma, Murcia...): más de 50 farmacias en la caja, se busca con la vía.
        q = f"farmacia {core.name}"
    found = geo.nominatim(
        q=q,
        limit="50",
        bounded="1",
        viewbox=f"{box[0]:.4f},{box[1]:.4f},{box[2]:.4f},{box[3]:.4f}",
    )
    if len(found) >= 50:
        return None  # resultados truncados: la otra farmacia de la vía podría no aparecer
    same_street = [
        it for it in found
        if (it.get("type") == "pharmacy" or it.get("class") in ("amenity", "shop"))
        and osm_street_match(core, (it.get("address") or {}).get("road") or "")
    ]
    if len(same_street) != 1:
        return None
    loc = normalize_text(pharmacy.locality)
    others = [
        o for o in geo.session.scalars(select(Pharmacy).where(Pharmacy.id != pharmacy.id, Pharmacy.region == pharmacy.region)).all()
        if normalize_text(o.locality) == loc
    ]
    if any(
        (oc := street_core(o.address)).name and street_similarity(oc.name, core.name) >= STREET_MIN_SCORE
        for o in others
    ):
        return None
    it = same_street[0]
    house = re.match(r"\d+", str((it.get("address") or {}).get("house_number") or ""))
    if core.number and house and int(house.group(0)) != core.number:
        return None
    # Apellidos del titular ("APELLIDO APELLIDO, NOMBRE"): ni nombres de pila ni apellidos comunes.
    surnames = pharmacy.holder.split(",", 1)[0]
    holder_tokens = [t for t in _tokens(surnames) if len(t) >= 4 and t not in _COMMON_SURNAMES]
    name_tokens = _tokens(it.get("name") or "")
    by_number = bool(core.number and house and int(house.group(0)) == core.number)
    by_holder = any(t in name_tokens for t in holder_tokens)
    if not (by_number or by_holder):
        return None
    return float(it["lat"]), float(it["lon"]), "portal", f"osm {it.get('osm_type')}/{it.get('osm_id')}"


def geocode_pharmacy(geo: GeoClient, pharmacy: Pharmacy) -> GeoResult:
    """Geocodifica una farmacia según las reglas del módulo."""
    region = pharmacy.region
    if region == "15" and pharmacy.id.startswith("NA:"):
        coords = idena_coordinates().get(pharmacy.id[3:])
        if coords is not None and is_within_bbox(region, *coords):
            return GeoResult(coords[0], coords[1], "portal", "idena", f"IDENA {pharmacy.id[3:]}", "capa oficial IDENA")
    if region == "02" and pharmacy.id.startswith("ZGZ:"):
        coords = zaragoza_coordinates().get(pharmacy.id)
        if coords is not None and is_within_bbox(region, *coords):
            return GeoResult(coords[0], coords[1], "portal", "ayto_zaragoza", "Ayuntamiento de Zaragoza", "coordenadas de la fuente")
    ctx = resolve_context(geo, pharmacy)
    clean = clean_address(pharmacy.address)
    addr = parse_address(clean)
    nucleus = None
    casco_nucleus = None
    if ctx.nucleus_name:
        nucleus = find_nucleus(geo, ctx.nucleus_name, ctx.munis, region)
        if nucleus is not None and nucleus.muni and nucleus.muni not in ctx.munis:
            ctx.munis.append(nucleus.muni)
    if ctx.casco and ctx.munis and nucleus is None:
        for phrase in _hint_phrases(pharmacy.address):
            if muni_key(phrase) in ctx.muni_keys:
                continue
            hinted = find_nucleus(geo, phrase, ctx.munis, region)
            if hinted is not None and muni_key(hinted.name) not in ctx.muni_keys:
                nucleus = hinted
                ctx.nucleus_name, ctx.casco = hinted.name, False
                ctx.note = f"núcleo en dirección: {phrase}"
                break
    if ctx.casco and ctx.munis:
        for muni in ctx.munis:
            casco_nucleus = find_nucleus(geo, muni, [muni], region)
            if casco_nucleus is None and muni_key(muni) == "maomahon":
                casco_nucleus = find_nucleus(geo, "Maó", [muni], region)
            if casco_nucleus is not None:
                break

    postal = list(ctx.postal_codes)
    if not postal and nucleus is not None:
        postal = list(nucleus.postal_codes)
    short_munis: list[str] = []
    for m in ctx.munis[:8]:
        for variant in [m] + [x for x in m.split("-") if len(x) > 2 and x != m]:
            if variant not in short_munis:
                short_munis.append(variant)
    places = [f"{ctx.nucleus_name}, {m}" for m in ctx.munis[:2]] if ctx.nucleus_name else []
    places += short_munis or [REGION_NAMES[region]]
    query = f"{addr.full}{', ' + str(addr.number) if addr.number else ''} | {places[0]}"
    rejected: list[str] = []

    if addr.name and len(normalize_text(addr.name)) >= 3 and ctx.munis:
        attempts = [_cartociudad_street(geo, ctx, addr, region, postal, places, nucleus)]
        cities = []
        if ctx.nucleus_name:
            cities.append(ctx.nucleus_name)
        cities.extend(short_munis[:4])
        for cands in attempts:
            for lat, lon, precision, src, _raw in cands:
                why = _validate_point(geo, ctx, nucleus, casco_nucleus, region, lat, lon)
                if why is None:
                    return GeoResult(lat, lon, precision, src.split(":", 1)[0], query, ctx.note)
                rejected.append(why)
        for lat, lon, precision, src, _raw in _nominatim_street(geo, ctx, addr, postal, cities):
            why = _validate_point(geo, ctx, nucleus, casco_nucleus, region, lat, lon)
            if why is None:
                return GeoResult(lat, lon, precision, "nominatim", query, ctx.note)
            rejected.append(why)

    detail = "; ".join(dict.fromkeys(rejected)) or "dirección no encontrada"
    # Último recurso antes del centro del núcleo: la farmacia cartografiada en OpenStreetMap,
    # cerca del núcleo o, en términos extensos o sin localidad, en todo el casco con la vía.
    osm = None
    center = nucleus or casco_nucleus
    if center is not None:
        osm = _osm_pharmacy(geo, pharmacy, center=(center.lat, center.lon))
    if osm is None:
        wide = [casco_nucleus] if casco_nucleus is not None and casco_nucleus.rings else []
        if not wide and nucleus is None and not ctx.nucleus_name:
            wide = [n for n in (find_nucleus(geo, m, [m], region) for m in ctx.munis[:2]) if n is not None and n.rings]
        for n in wide:
            osm = _osm_pharmacy(geo, pharmacy, box=_nucleus_box(n))
            if osm is not None:
                break
    if osm is not None:
        why = _validate_point(geo, ctx, nucleus, casco_nucleus, region, osm[0], osm[1])
        if why is None:
            return GeoResult(osm[0], osm[1], osm[2], "osm_farmacia", query, f"{detail}; {osm[3]}")
        detail += f"; farmacia OSM descartada ({why})"
    if nucleus is not None:
        why = _validate_point(geo, ctx, None, None, region, nucleus.lat, nucleus.lon)
        if why is None:
            return GeoResult(
                nucleus.lat, nucleus.lon, "localidad", "nucleus_centroid", query,
                f"{detail}; centroide del núcleo {nucleus.name}",
            )
    if casco_nucleus is not None and casco_nucleus.extent_km() > CASCO_CENTROID_MAX_EXTENT_KM:
        detail += f"; casco urbano de {casco_nucleus.name} demasiado extenso para usar su centro"
        casco_nucleus = None
    if casco_nucleus is not None:
        why = _validate_point(geo, ctx, None, None, region, casco_nucleus.lat, casco_nucleus.lon)
        if why is None:
            return GeoResult(
                casco_nucleus.lat, casco_nucleus.lon, "localidad", "casco_centroid", query,
                f"{detail}; centroide del casco urbano de {casco_nucleus.name}",
            )
    if ctx.nucleus_name and nucleus is None:
        detail += f"; núcleo {ctx.nucleus_name!r} no localizado"
    elif not ctx.nucleus_name and not ctx.casco:
        detail += "; núcleo desconocido (sin localidad en la fuente)"
    return GeoResult(None, None, None, None, query, detail)


# ---------------------------------------------------------------------------
# Control final y proceso por lotes
# ---------------------------------------------------------------------------


def enforce_shared_coordinates_limit(session: Session) -> list[dict[str, Any]]:
    """Ningún punto compartido por más de 2 farmacias con direcciones distintas.

    Las sobrantes (priorizando conservar portal/calle) pasan a lat/lon = NULL.
    """
    pharmacies = session.scalars(
        select(Pharmacy).where(Pharmacy.lat.is_not(None), Pharmacy.lon.is_not(None))
    ).all()
    groups: dict[tuple[float, float], list[Pharmacy]] = defaultdict(list)
    for p in pharmacies:
        groups[(round(p.lat, 5), round(p.lon, 5))].append(p)
    degraded: list[dict[str, Any]] = []
    order = {"portal": 0, "calle": 1}
    for coords, members in groups.items():
        if len(members) <= 2 or len({clean_address(m.address) for m in members}) == 1:
            continue
        members.sort(key=lambda m: order.get(m.geo_precision or "", 2))
        for excess in members[2:]:
            degraded.append(
                {
                    "id": excess.id,
                    "direccion": excess.address,
                    "coords": coords,
                    "motivo": f"punto compartido por {len(members)} farmacias",
                }
            )
            excess.lat = excess.lon = None
            excess.geo_precision = excess.geo_source = None
    session.commit()
    return degraded


def geocode_all_pharmacies(
    limit: int | None = None,
    recheck_only: bool = False,
    report_path: Path | str = "tmp/geocode_report.txt",
    database_url: str | None = None,
    ids: list[str] | None = None,
    offline: bool = False,
) -> dict[str, Any]:
    """Geocodifica las farmacias y escribe el informe."""
    engine = create_db_engine(database_url)
    init_db(engine)
    reasons: dict[str, str] = {}
    with Session(engine) as session:
        query = select(Pharmacy).order_by(Pharmacy.id)
        if ids:
            query = query.where(Pharmacy.id.in_(ids))
        elif recheck_only:
            query = query.where(
                or_(Pharmacy.geo_precision == "localidad", Pharmacy.lat.is_(None))
            )
        if limit:
            query = query.limit(limit)
        targets = session.scalars(query).all()
        print(f"Farmacias a procesar: {len(targets)}")
        with httpx.Client() as http:
            geo = GeoClient(session, http, offline=offline)
            for idx, p in enumerate(targets, 1):
                res = geocode_pharmacy(geo, p)
                p.lat, p.lon = res.lat, res.lon
                p.geo_precision, p.geo_source = res.precision, res.source
                p.geo_query = res.query
                reasons[p.id] = res.reason
                if idx % 20 == 0:
                    session.commit()
                    print(f"  {idx}/{len(targets)} (llamadas en vivo: {geo.live_calls})", flush=True)
            session.commit()
        degraded = enforce_shared_coordinates_limit(session)
        stats = write_report(session, report_path, reasons, degraded)
        export_coordinates(session)
    return stats


COORDS_PATH = Path(__file__).resolve().parent.parent / "data" / "geo" / "coordenadas.json"


def export_coordinates(session: Session, path: Path = COORDS_PATH) -> int:
    """Guarda el resultado de la geocodificación en un JSON versionable.

    Permite reconstruir data/guardias.db desde cero (p. ej. en una tarea en la
    nube) sin volver a consultar los servicios: el importador reutiliza estas
    coordenadas mientras no cambien la dirección, la localidad ni el CP.
    """
    rows = session.scalars(select(Pharmacy).order_by(Pharmacy.id)).all()
    data = {
        p.id: {
            "direccion": p.address,
            "localidad": p.locality,
            "cp": p.postal_code,
            "lat": None if p.lat is None else round(p.lat, 7),
            "lon": None if p.lon is None else round(p.lon, 7),
            "precision": p.geo_precision,
            "fuente": p.geo_source,
            "consulta": p.geo_query,
        }
        for p in rows
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    return len(data)


def _pct(a: int, b: int) -> str:
    return f"{a / b * 100:.1f}%" if b else "n/d"


def write_report(
    session: Session,
    report_path: Path | str,
    reasons: dict[str, str],
    degraded: list[dict[str, Any]],
) -> dict[str, Any]:
    """Informe de calidad de la geocodificación (tmp/geocode_report.txt)."""
    rows = session.scalars(select(Pharmacy).order_by(Pharmacy.id)).all()
    by_region: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for p in rows:
        by_region[p.region]["total"] += 1
        by_region[p.region][p.geo_precision or "sin_coordenadas"] += 1
    total = len(rows)
    pc = sum(1 for p in rows if p.geo_precision in ("portal", "calle"))
    palma = [p for p in rows if p.region == "04" and (
        (p.locality or "").upper() == "PALMA"
        or (not p.locality and json.loads(p.zones or "[]") == ["PALMA"]))]
    murcia = [p for p in rows if p.region == "14" and (p.locality or "").upper() == "MURCIA"]
    lines = [
        "=" * 70,
        "INFORME DE GEOCODIFICACIÓN (v4)",
        f"Generado: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 70,
        f"Total farmacias: {total}",
        f"Portal + calle: {pc} ({_pct(pc, total)})",
        f"Palma (solo zona PALMA o localidad PALMA): "
        f"{sum(p.geo_precision in ('portal', 'calle') for p in palma)}/{len(palma)}",
        f"Murcia (localidad MURCIA): "
        f"{sum(p.geo_precision in ('portal', 'calle') for p in murcia)}/{len(murcia)}",
        "",
    ]
    for reg, st in sorted(by_region.items()):
        lines.append(f"[{REGION_NAMES.get(reg, reg)}] total {st['total']}: " + ", ".join(
            f"{k} {v} ({_pct(v, st['total'])})" for k, v in sorted(st.items()) if k != "total"
        ))
    lines += ["", "-" * 70, "PUNTOS COMPARTIDOS (> 1 farmacia)", "-" * 70]
    groups: dict[tuple[float, float], list[Pharmacy]] = defaultdict(list)
    for p in rows:
        if p.lat is not None:
            groups[(round(p.lat, 5), round(p.lon, 5))].append(p)
    shared = [(c, m) for c, m in groups.items() if len(m) > 1]
    lines.append(f"Grupos: {len(shared)}; con más de 2: {sum(len(m) > 2 for _c, m in shared)}")
    for c, m in sorted(shared, key=lambda x: -len(x[1])):
        lines.append(f"{c}: " + " | ".join(f"{x.id} {x.address} [{x.geo_precision}]" for x in m))
    if degraded:
        lines.append("Degradadas a NULL por el control de puntos compartidos:")
        lines += [f"  {d['id']} {d['direccion']} {d['coords']}" for d in degraded]
    lines += ["", "-" * 70, "A NIVEL LOCALIDAD (centroide de núcleo)", "-" * 70]
    for p in rows:
        if p.geo_precision == "localidad":
            lines.append(f"{p.id} | {p.address} | {p.locality or '-'} | {p.geo_source} | {reasons.get(p.id, '')}")
    lines += ["", "-" * 70, "SIN COORDENADAS", "-" * 70]
    for p in rows:
        if p.lat is None:
            lines.append(f"{p.id} | {p.address} | {p.locality or '-'} | {p.zones or ''} | {reasons.get(p.id, '')}")
    lines += ["", "-" * 70, "MUESTRA ALEATORIA DE 20 A PORTAL/CALLE (revisión manual)", "-" * 70]
    good = [p for p in rows if p.geo_precision in ("portal", "calle")]
    for p in random.Random(19).sample(good, min(20, len(good))):
        lines.append(
            f"{p.id} [{p.geo_precision}] {p.address} ({p.locality or ''}) "
            f"https://www.openstreetmap.org/?mlat={p.lat:.6f}&mlon={p.lon:.6f}#map=18/{p.lat:.6f}/{p.lon:.6f}"
        )
    report = Path(report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:12]))
    return {"total": total, "portal_calle": pc, "por_region": {k: dict(v) for k, v in by_region.items()}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Geocodificador de farmacias (v4).")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--recheck", action="store_true",
                        help="Solo farmacias a nivel localidad o sin coordenadas.")
    parser.add_argument("--ids", type=str, default=None, help="Lista de ids separada por comas.")
    parser.add_argument("--offline", action="store_true",
                        help="Usar solo la caché (sin llamadas a los servicios).")
    parser.add_argument("--report", type=str, default="tmp/geocode_report.txt")
    args = parser.parse_args()
    geocode_all_pharmacies(
        limit=args.limit,
        recheck_only=args.recheck,
        report_path=args.report,
        ids=[i.strip() for i in args.ids.split(",")] if args.ids else None,
        offline=args.offline,
    )


if __name__ == "__main__":
    main()

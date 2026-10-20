"""Tests del geocodificador v4: utilidades puras y calidad de data/guardias.db."""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import pytest

from backend.geocode import (
    Nucleus,
    _hint_phrases,
    _point_in_ring,
    baleares_municipality,
    clean_address,
    muni_key,
    muni_matches,
    parse_address,
    street_similarity,
)
from backend.importer import import_source_data  # noqa: F401  (el módulo debe importar)

DB_PATH = Path("data/guardias.db")
ALLOWED_SOURCES = {
    "cartociudad", "nominatim", "nucleus_centroid", "casco_centroid", "idena", "ayto_zaragoza", "osm_farmacia",
}


def test_muni_matches_es_exacto_y_no_por_subcadena():
    assert muni_matches("Murcia", "Murcia")
    assert not muni_matches("Murcia", "Alhama de Murcia")
    assert not muni_matches("Palma", "Palmanova")
    assert muni_matches("Maó-Mahón", "Maó")
    assert muni_matches("Santa Eulària des Riu", "Santa Eulalia del Río")
    assert muni_matches("Es Mercadal", "Mercadal, Es")
    assert muni_matches("Torre-Pacheco", "Torre Pacheco")
    assert muni_matches("Fuente Álamo", "Fuente Álamo de Murcia")
    assert muni_key("Ciutadella") == muni_key("Ciutadella de Menorca")


def test_municipios_baleares():
    assert baleares_municipality("VILLAFRANCA") == "Vilafranca de Bonany"
    assert baleares_municipality("SANTANYÍ") == "Santanyí"
    assert baleares_municipality("CA'N PICAFORT") is None


def test_parse_address():
    a = parse_address(clean_address("CL.CAMINO REAL, Nº 31-IFRE-CAÑADA DE GALLEGO"))
    assert (a.street_type, a.name, a.number) == ("CAMINO", "REAL", 31)
    a = parse_address(clean_address("AV AVINGUDA DE CARLES V, 16 B"))
    assert (a.street_type, a.name, a.number) == ("AVENIDA", "DE CARLES V", 16)
    a = parse_address(clean_address("PLAZA DEL TRABAJO, Nº 1, URBANIZACION LA VIÑA"))
    assert (a.name, a.number) == ("DEL TRABAJO", 1)
    a = parse_address(clean_address("DR. ORFILA, 28"))
    assert (a.name, a.number) == ("DOCTOR ORFILA", 28)


def test_street_similarity():
    assert street_similarity("CRISTOBAL COLOM", "AVINGUDA CRISTÒFOL COLOM") >= 0.6
    assert street_similarity("JUAN SERVERA CAMPS", 'AVINGUDA D"EN JOAN SERVERA CAMPS') >= 0.6
    assert street_similarity("DOCTOR ORFILA", "CALLE DEL DOCTOR CAMPS") < 0.6
    assert street_similarity("CANOVAS", "CALLE CANOVAS DEL CASTILLO") >= 0.6
    assert street_similarity("SAN JOSE", "CALLE JOSE ANTONIO PRIMO") < 0.6
    assert street_similarity("MAYOR", "CALLE MAYOR") == 1.0


def test_street_core_y_vias_osm():
    from backend.geocode import osm_street_match, street_core

    assert street_core("CL FALZIA, s/n - URB. PUIG DE ROS").name == "FALZIA"
    assert street_core("AVD. DE LAS PALMERAS-EDIF. CORAL").street_type == "AVENIDA"
    assert street_core("AVENIDA MONTE AZAHAR, Nº 4").number == 4
    assert street_core("PASEO DEL MAR, Ed. Zorba LOCAL 32").number is None  # no es el portal
    assert osm_street_match(street_core("AVENIDA MONTE AZAHAR, Nº 4"), "Avenida Monteazahar")
    assert osm_street_match(street_core("CL FALZIA, s/n"), "carrer Falzia")
    assert osm_street_match(street_core("AVD. DE LA PLAYA, 1 LOCAL 32"), "Avinguda de la Platja")
    # Distinto tipo de vía: no es la misma.
    assert not osm_street_match(street_core("C/FORTUNA,2 URB.LAS PALOMAS"), "Plaza de Fortuna")
    assert not osm_street_match(street_core("DR. ORFILA, 28"), "Carrer Gran")


class _GeoStub:
    """GeoClient mínimo para probar _osm_pharmacy sin red."""

    def __init__(self, found, others):
        self._found = found

        class _S:
            def scalars(self, _q):
                class _R:
                    def all(self_inner):
                        return others
                return _R()
        self.session = _S()

    def nominatim(self, **_params):
        return self._found


def _osm(road, number=None, name="", lat=39.6, lon=2.6):
    return {"type": "pharmacy", "class": "amenity", "lat": str(lat), "lon": str(lon), "name": name,
            "osm_type": "node", "osm_id": 1, "address": {"road": road, "house_number": number}}


def test_osm_farmacia_solo_con_identificacion_positiva():
    from backend.geocode import _osm_pharmacy
    from backend.models import Pharmacy

    p = Pharmacy(id="IB:x", region="04", holder="TINOCO GIL", address="AV GABRIEL ALOMAR, 27", locality=None)
    otra = Pharmacy(id="IB:y", region="04", holder="X", address="CL ARAGO, 70", locality=None)
    centro = (39.57, 2.65)
    # Mismo número: se acepta como portal.
    assert _osm_pharmacy(_GeoStub([_osm("Avinguda de Gabriel Alomar", "27")], [otra]), p, center=centro)[2] == "portal"
    # Número distinto: es otra farmacia de la misma vía.
    assert _osm_pharmacy(_GeoStub([_osm("Avinguda de Gabriel Alomar", "5")], [otra]), p, center=centro) is None
    # Sin número ni apellido en el nombre: no hay identificación positiva.
    assert _osm_pharmacy(_GeoStub([_osm("Avinguda de Gabriel Alomar")], [otra]), p, center=centro) is None
    # Apellido no común del titular en el nombre OSM: portal.
    assert _osm_pharmacy(_GeoStub([_osm("Avinguda de Gabriel Alomar", name="Farmacia Tinoco")], [otra]), p, center=centro)
    # Dos farmacias OSM en la vía, o resultados truncados: ambiguo.
    dos = [_osm("Avinguda de Gabriel Alomar", "27"), _osm("Avinguda de Gabriel Alomar", "40")]
    assert _osm_pharmacy(_GeoStub(dos, [otra]), p, center=centro) is None
    assert _osm_pharmacy(_GeoStub([_osm("Avinguda de Gabriel Alomar", "27")] + [_osm("Carrer X")] * 49, [otra]), p, center=centro) is None
    # Otra farmacia de la fuente en la misma vía y localidad (también sin localidad): ambiguo.
    vecina = Pharmacy(id="IB:z", region="04", holder="Y", address="AV GABRIEL ALOMAR, 3", locality=None)
    assert _osm_pharmacy(_GeoStub([_osm("Avinguda de Gabriel Alomar", "27")], [vecina]), p, center=centro) is None
    # Un nombre de pila del titular no identifica.
    q = Pharmacy(id="MU:x", region="14", holder="BRIONES ORTEGA, CARLOS", address="AVENIDA GENERAL ORTIN", locality="MURCIA")
    assert _osm_pharmacy(_GeoStub([_osm("Avenida General Ortín", name="Farmacia Carlos")], []), q, center=centro) is None
    assert _osm_pharmacy(_GeoStub([_osm("Avenida General Ortín", name="Briones")], []), q, center=centro)


def test_hint_phrases():
    assert "CALA MILLOR" in _hint_phrases("CRISTOBAL COLOM, 11 CALA MILLOR")
    assert "CAÑADA DE GALLEGO" in _hint_phrases("CL.CAMINO REAL, Nº 31-IFRE-CAÑADA DE GALLEGO")
    assert "SA COMA" in _hint_phrases("ATZEROLES, 2 SA COMA (Davant Hotel Mediterraneo)")
    assert "PUENTE TOCINOS" in _hint_phrases("MAYOR,104 - PUENTE TOCINOS")
    # Referencias que no son núcleos no se proponen
    assert not any(p.upper().startswith("JUNTO") for p in _hint_phrases("CL X, 1 (Junto Plaza Madrid)"))


def test_point_in_polygon_y_distancia():
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert _point_in_ring(0.5, 0.5, ring)
    assert not _point_in_ring(1.5, 0.5, ring)
    nuc = Nucleus("X", "Y", 0.5, 0.5, rings=[ring])
    assert nuc.distance_km(0.5, 0.5) == 0.0
    assert nuc.distance_km(0.5, 1.01) < 2.0


def _rows():
    if not DB_PATH.exists():
        pytest.skip("data/guardias.db no existe aún")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM pharmacies").fetchall()
    conn.close()
    return rows


def test_fuentes_y_precisiones_validas():
    for r in _rows():
        if r["lat"] is None:
            assert r["geo_precision"] is None and r["geo_source"] is None, r["id"]
            continue
        assert r["geo_source"] in ALLOWED_SOURCES, (r["id"], r["geo_source"])
        if r["geo_source"] in ("nucleus_centroid", "casco_centroid"):
            assert r["geo_precision"] == "localidad", r["id"]
        else:
            assert r["geo_precision"] in ("portal", "calle"), r["id"]


def test_ninguna_pedania_en_centroide_del_casco():
    """El centroide del casco urbano solo se usa si la fuente da localidad = municipio."""
    for r in _rows():
        if r["geo_source"] != "casco_centroid":
            continue
        loc = (r["locality"] or "").strip()
        assert loc, f"{r['id']} sin localidad en la fuente y situada en el casco urbano"
        assert "(" not in loc and "-" not in loc, f"{r['id']} ({loc}) es una pedanía"


def test_sin_puntos_compartidos_por_mas_de_dos():
    groups = defaultdict(list)
    for r in _rows():
        if r["lat"] is not None:
            groups[(round(r["lat"], 5), round(r["lon"], 5))].append(r)
    bad = {
        k: [x["id"] for x in v]
        for k, v in groups.items()
        if len(v) > 2 and len({clean_address(x["address"]) for x in v}) > 1
    }
    assert not bad, bad


def test_cala_millor_no_en_centroide_municipal():
    """Las farmacias de Cala Millor no pueden compartir punto con el centro de Son Servera."""
    rows = {r["id"]: r for r in _rows()}
    a, b = rows["IB:5b84a70432fe"], rows["IB:874b27557b01"]
    assert a["lat"] is not None and b["lat"] is not None
    assert (round(a["lat"], 4), round(a["lon"], 4)) != (round(b["lat"], 4), round(b["lon"], 4))
    assert a["geo_precision"] in ("portal", "calle") and b["geo_precision"] in ("portal", "calle")


def test_zonas_guardadas_en_baleares():
    for r in _rows():
        if r["region"] == "04":
            assert json.loads(r["zones"] or "[]"), r["id"]

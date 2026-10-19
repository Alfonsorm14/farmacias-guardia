"""Tests de la API backend de farmacias de guardia (sin red, coordenadas inyectadas)."""
from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.importer import import_all
from backend.models import Pharmacy, Shift


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["pharmacies"] > 0
    assert data["shifts"] > 0


def test_palma_nocturnas(client: TestClient):
    """Palma (39.5696, 2.6502), at=2026-10-18T23:00+02:00 -> exactamente las 3 nocturnas de Palma

    (ALCOVER CASASNOVAS, R; GOMEZ GARCIA; REAL VICENS), horario_confirmado true.
    """
    response = client.get(
        "/v1/guardias",
        params={
            "lat": 39.5696,
            "lon": 2.6502,
            "at": "2026-10-18T23:00:00+02:00",
            "radius_km": 25,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["cobertura"] is True
    assert data["mensaje"] is None

    guardias = data["guardias"]
    assert len(guardias) == 3

    titulares = {g["farmacia"]["titular"] for g in guardias}
    assert any("ALCOVER" in t for t in titulares)
    assert any("GOMEZ" in t for t in titulares)
    assert any("REAL VICENS" in t for t in titulares)

    for g in guardias:
        assert g["turno"]["horario_confirmado"] is True
        assert g["turno"]["tipo"] == "nocturna"
        assert g["turno"]["zona"] == "PALMA"


def test_palma_diurnas(client: TestClient):
    """Palma, at=2026-10-18T12:00+02:00 -> incluye las 19 diurnas de Palma."""
    response = client.get(
        "/v1/guardias",
        params={
            "lat": 39.5696,
            "lon": 2.6502,
            "at": "2026-10-18T12:00:00+02:00",
            "radius_km": 25,
            "limit": 50,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["cobertura"] is True

    guardias = data["guardias"]
    palma_diurnas = [
        g
        for g in guardias
        if g["turno"]["zona"] == "PALMA" and g["turno"]["tipo"] == "diurna"
    ]
    assert len(palma_diurnas) == 19


def test_alcantarilla_inexact(client: TestClient):
    """Alcantarilla (37.969, -1.217), at=2026-01-01T03:00+01:00 -> MU:431, horario_confirmado false."""
    response = client.get(
        "/v1/guardias",
        params={
            "lat": 37.969,
            "lon": -1.217,
            "at": "2026-01-01T03:00:00+01:00",
            "radius_km": 25,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["cobertura"] is True

    guardias = data["guardias"]
    mu431_guardia = next(
        (g for g in guardias if g["farmacia"]["id"] == "MU:431"), None
    )
    assert mu431_guardia is not None
    assert mu431_guardia["turno"]["horario_confirmado"] is False


def test_burgos_sin_cobertura(client: TestClient):
    """Burgos (42.344, -3.696) -> cobertura false, lista vacía, mensaje 'Sin datos oficiales para esta zona'."""
    response = client.get(
        "/v1/guardias",
        params={
            "lat": 42.344,
            "lon": -3.696,
            "radius_km": 25,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["cobertura"] is False
    assert len(data["guardias"]) == 0
    assert data["mensaje"] == "Sin datos oficiales para esta zona"


def test_mazarron_sin_turnos_esta_fecha(client: TestClient):
    """Mazarrón (37.598, -1.314), fecha 2026-10-18 -> cobertura true, lista vacía,

    mensaje 'Sin datos oficiales para esta fecha' (agrupación sin cuadrante: decisión de producto).
    """
    response = client.get(
        "/v1/guardias/dia",
        params={
            "lat": 37.598,
            "lon": -1.314,
            "fecha": "2026-10-18",
            "radius_km": 25,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["cobertura"] is True
    assert len(data["guardias"]) == 0
    assert data["mensaje"] == "Sin datos oficiales para esta fecha"


def test_dst_cambio_hora_12h(db_session: Session):
    """Cambio de hora: un turno nocturno 2026-10-24 22:00 -> 2026-10-25 09:00 Europe/Madrid dura 12 h reales."""
    madrid_tz = ZoneInfo("Europe/Madrid")
    st = datetime.datetime(2026, 10, 24, 22, 0, 0, tzinfo=madrid_tz)
    st_utc = st.astimezone(datetime.timezone.utc)

    # Buscar turno en DB con inicio el 2026-10-24 22:00 Madrid
    shift = (
        db_session.query(Shift)
        .filter(Shift.start_utc == st_utc, Shift.kind == "nocturna")
        .first()
    )
    assert shift is not None

    duration_seconds = (shift.end_utc - shift.start_utc).total_seconds()
    duration_hours = duration_seconds / 3600.0
    assert duration_hours == 12.0


def test_importador_idempotente(session_factory):
    """Importador idempotente: importar dos veces no duplica turnos ni pierde coordenadas."""
    with session_factory() as session:
        initial_shifts_count = session.query(Shift).count()
        p = session.get(Pharmacy, "IB:0efd04c9a719")
        assert p.lat is not None
        saved_lat = p.lat
        saved_lon = p.lon

    # Segunda importación sobre la misma BD
    import_all("data/out", session_factory=session_factory)

    with session_factory() as session:
        after_shifts_count = session.query(Shift).count()
        assert after_shifts_count == initial_shifts_count

        p_after = session.get(Pharmacy, "IB:0efd04c9a719")
        assert p_after.lat == saved_lat
        assert p_after.lon == saved_lon


def test_farmacia_detalle_y_fuentes(client: TestClient):
    """Ficha de farmacia con próximos 3 turnos y endpoint de fuentes."""
    # Farmacia existente
    res = client.get("/v1/farmacias/IB:0efd04c9a719")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "IB:0efd04c9a719"
    assert "titular" in data
    assert "proximos_turnos" in data
    assert isinstance(data["proximos_turnos"], list)
    assert len(data["proximos_turnos"]) <= 3

    # Farmacia inexistente
    res_404 = client.get("/v1/farmacias/NO_EXISTE")
    assert res_404.status_code == 404

    # Fuentes
    res_fuentes = client.get("/v1/fuentes")
    assert res_fuentes.status_code == 200
    fuentes = res_fuentes.json()
    assert len(fuentes) >= 2
    for f in fuentes:
        assert "publisher" in f
        assert "license" in f
        assert "url" in f
        assert f["municipal"] is (f["source_id"] in {"MAD-AYTO-DATOSABIERTOS", "ZGZ-AYTO"})


def test_limpieza_api_claves_sin_tildes_y_sin_duplicados(client: TestClient):
    """Verifica limpieza de la API: solo lista guardias (sin turnos ni resultados)

    y claves de farmacia sin tildes únicamente (direccion, telefono, telefono_guardia).
    """
    response = client.get(
        "/v1/guardias",
        params={
            "lat": 39.5696,
            "lon": 2.6502,
            "at": "2026-10-18T23:00:00+02:00",
            "radius_km": 25,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "guardias" in data
    assert "turnos" not in data
    assert "resultados" not in data

    for item in data["guardias"]:
        farm = item["farmacia"]
        assert "direccion" in farm
        assert "dirección" not in farm
        assert "telefono" in farm
        assert "teléfono" not in farm
        assert "telefono_guardia" in farm
        assert "teléfono_guardia" not in farm


def test_normalizacion_direcciones():
    """Test de normalización de direcciones con 8 ejemplos reales del informe."""
    from backend.geocode import clean_address

    casos = [
        ("GRAN VIA, Nº 2,ESQUINA A CALLE MAYOR", "GRAN VIA, 2"),
        ("PLAZA MIGUEL DE CERVANTES, Nº 1-LOS NAREJOS", "PLAZA MIGUEL DE CERVANTES, 1"),
        ("CL.ALFREDO NOVEL, Nº 1", "CALLE ALFREDO NOVEL, 1"),
        ("AVDA.REINO DE MURCIA, S/N", "AVENIDA REINO DE MURCIA"),
        ("C/SON RAPINYA, 31 LOC. 7,8 (Rotonda Colegios)", "CALLE SON RAPINYA, 31"),
        ("AVDA, S'OLIVERA, 11, Local 9", "AVENIDA S'OLIVERA, 11"),
        ("CTRA.ARCHENA-FORTUNA, Km. 6", "CARRETERA ARCHENA-FORTUNA, Km. 6"),
        ("C/ IMPERIAL, 2 , LOCAL - 2", "CALLE IMPERIAL, 2"),
    ]

    for raw, expected in casos:
        resultado = clean_address(raw)
        assert resultado == expected, f"Fallo al normalizar: '{raw}' -> '{resultado}', esperado '{expected}'"


def test_no_farmacias_con_coordenadas_de_test_conftest():
    """Verifica que ninguna farmacia de la base de datos real data/guardias.db

    tenga coordenadas idénticas a cualquier coordenada inyectada o usada en conftest.py.
    """
    import sqlite3
    from pathlib import Path

    test_coords = [
        (39.5696, 2.6502),  # Coordenada fija de Palma de la Tarea 03
        (37.969, -1.217),   # Alcantarilla test inyectada
        (37.598, -1.314),   # Mazarrón test inyectada
        (39.5740, 2.6626),  # Alcover Casasnovas
        (39.5701, 2.6512),  # Real Vicens
        (39.5685, 2.6491),  # Gomez Garcia
    ]

    db_path = Path("data/guardias.db")
    if not db_path.exists():
        pytest.skip("data/guardias.db no existe aún")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    violaciones = []
    for lat, lon in test_coords:
        cur.execute(
            "SELECT id, holder, address, lat, lon FROM pharmacies WHERE abs(lat - ?) < 0.00001 AND abs(lon - ?) < 0.00001",
            (lat, lon),
        )
        rows = cur.fetchall()
        for r in rows:
            violaciones.append(r)
    conn.close()

    assert not violaciones, f"Farmacias con coordenadas de test de conftest.py detectadas: {violaciones}"


def test_los_belones_mu302_cerca_de_su_nucleo():
    """MU:302 (Los Belones) debe estar a menos de 5 km del núcleo de Los Belones

    y no en el centro de Cartagena (> 15 km).
    """
    import sqlite3
    from pathlib import Path
    from backend.geocode import haversine_km

    db_path = Path("data/guardias.db")
    if not db_path.exists():
        pytest.skip("data/guardias.db no existe aún")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, lat, lon, geo_precision FROM pharmacies WHERE id = 'MU:302'")
    row = cur.fetchone()
    conn.close()

    assert row is not None, "Farmacia MU:302 no encontrada"
    pid, lat, lon, prec = row
    assert lat is not None and lon is not None, "MU:302 no tiene coordenadas asignadas"

    # Coordenadas reales del núcleo de Los Belones (lat ~37.6247, lon ~-0.7762)
    belones_lat, belones_lon = 37.62474, -0.77618
    dist_nucleo = haversine_km(lat, lon, belones_lat, belones_lon)
    assert dist_nucleo < 5.0, f"MU:302 dista {dist_nucleo:.2f} km de Los Belones (> 5 km)"

    # Verificar que NO está en el centroide de Cartagena (37.6056, -0.9863)
    dist_cartagena = haversine_km(lat, lon, 37.6056, -0.9863)
    assert dist_cartagena > 10.0, f"MU:302 erróneamente en el centro de Cartagena ({dist_cartagena:.2f} km)"


def test_api_ubicacion_aproximada_flag(client: TestClient):
    """Verifica que la API incluya ubicacion_aproximada en las farmacias."""
    resp = client.get("/v1/farmacias/IB:0efd04c9a719")
    assert resp.status_code == 200
    data = resp.json()
    assert "ubicacion_aproximada" in data
    assert isinstance(data["ubicacion_aproximada"], bool)

    # Consulta de guardias
    resp_g = client.get("/v1/guardias?lat=39.5696&lon=2.6502&at=2026-01-01T23:00:00%2B01:00&radius_km=15")
    assert resp_g.status_code == 200
    data_g = resp_g.json()
    if data_g.get("guardias"):
        first_farm = data_g["guardias"][0]["farmacia"]
        assert "ubicacion_aproximada" in first_farm
        assert isinstance(first_farm["ubicacion_aproximada"], bool)




def test_madrid_capital_tiene_guardias(client: TestClient):
    """Puerta del Sol, 1/10/2026 a las 12:00: guardias diurnas de la fuente municipal de Madrid."""
    response = client.get(
        "/v1/guardias",
        params={"lat": 40.4169, "lon": -3.7035, "at": "2026-10-01T12:00:00+02:00", "radius_km": 5},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["cobertura"] is True
    assert data["guardias"], data
    assert all(g["farmacia"]["id"].startswith("MAD:") for g in data["guardias"])
    assert data["datos_hasta"] is not None


def test_fuente_municipal_no_vale_fuera_del_termino(client: TestClient):
    """Alcalá de Henares (a ~30 km) y Getafe (a ~13 km del centro): las farmacias de Madrid capital
    no son su guardia. Getafe queda dentro de 25 km de muchas farmacias de Madrid, pero fuera de
    la caja de la fuente municipal ampliada en 2 km -> sin cobertura."""
    for lat, lon in ((40.4818, -3.3643), (40.3083, -3.7327)):
        response = client.get(
            "/v1/guardias",
            params={"lat": lat, "lon": lon, "at": "2026-10-01T12:00:00+02:00", "radius_km": 25},
        )
        data = response.json()
        assert not any(g["farmacia"]["id"].startswith("MAD:") for g in data["guardias"]), (lat, lon)
        assert data["cobertura"] is False
        assert data["mensaje"] == "Sin datos oficiales para esta zona"


def test_fecha_aun_no_publicada(client: TestClient):
    """Palma en 2030: hay cobertura, pero la fuente aún no ha publicado turnos para esa fecha."""
    response = client.get(
        "/v1/guardias/dia",
        params={"lat": 39.5696, "lon": 2.6502, "fecha": "2030-06-01", "radius_km": 25},
    )
    data = response.json()
    assert data["cobertura"] is True
    assert data["guardias"] == []
    assert data["mensaje"] == "Aún no hay turnos oficiales publicados para esta fecha"
    assert data["datos_hasta"].startswith("2026-") or data["datos_hasta"].startswith("2027-")


def test_inside_box_margen():
    from backend.ambito import inside_box

    box = (40.0, -4.0, 40.5, -3.5)
    assert inside_box(box, 40.25, -3.75)
    assert inside_box(box, 40.51, -3.75)  # ~1,1 km fuera: dentro del margen de 2 km
    assert not inside_box(box, 40.55, -3.75)  # ~5,5 km fuera
    assert not inside_box(None, 40.25, -3.75)

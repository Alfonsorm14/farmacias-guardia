"""Fixtures para los tests de pytest con base de datos real importada y coordenadas inyectadas."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from backend.api import app
from backend.db import create_db_engine, get_db, init_db
from backend.importer import import_all
from backend.models import Pharmacy, Shift

TEST_DB_PATH = Path("tmp") / "test_suite.db"
TEST_DB_URL = f"sqlite:///{TEST_DB_PATH.as_posix()}"


@pytest.fixture(scope="session")
def engine():
    if TEST_DB_PATH.exists():
        try:
            TEST_DB_PATH.unlink()
        except OSError:
            pass

    eng = create_db_engine(TEST_DB_URL)
    init_db(eng)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=eng)

    # 1. Importar los JSONs reales de data/out
    import_all("data/out", session_factory=session_factory, reuse_coordinates=False)

    # 2. Inyectar coordenadas para los casos de test
    with session_factory() as session:
        with session.begin():
            # Palma (39.5696, 2.6502)
            # Farmacias nocturnas específicas
            nocturnas = {
                "IB:0efd04c9a719": (39.5740, 2.6626),  # ALCOVER CASASNOVAS, R
                "IB:d44f25d79c0c": (39.5701, 2.6512),  # REAL VICENS
                "IB:fadab7b77a9e": (39.5685, 2.6491),  # GOMEZ GARCIA
            }
            for pid, (lat, lon) in nocturnas.items():
                p = session.get(Pharmacy, pid)
                if p:
                    p.lat = lat
                    p.lon = lon
                    p.geo_precision = "portal"
                    p.geo_source = "test_injected"

            # Todas las demás farmacias que tengan turnos en zona PALMA
            palma_shifts = (
                session.query(Shift.pharmacy_id)
                .filter(Shift.zone == "PALMA")
                .distinct()
                .all()
            )
            offset = 0.001
            for (pid,) in palma_shifts:
                if pid not in nocturnas:
                    p = session.get(Pharmacy, pid)
                    if p:
                        p.lat = 39.5696 + offset
                        p.lon = 2.6502 + offset
                        p.geo_precision = "calle"
                        p.geo_source = "test_injected"
                        offset += 0.0005

            # Alcantarilla (37.969, -1.217) -> MU:431
            mu431 = session.get(Pharmacy, "MU:431")
            if mu431:
                mu431.lat = 37.969
                mu431.lon = -1.217
                mu431.geo_precision = "portal"
                mu431.geo_source = "test_injected"

            # Mazarrón (37.598, -1.314) -> Farmacias de Mazarrón
            mazarron_pharmacies = (
                session.query(Pharmacy)
                .filter(Pharmacy.locality.ilike("%mazarr%"))
                .all()
            )
            for p in mazarron_pharmacies:
                p.lat = 37.598
                p.lon = -1.314
                p.geo_precision = "localidad"
                p.geo_source = "test_injected"

            # Madrid capital: coordenadas reales ya calculadas (fuente municipal, ámbito acotado).
            known = json.loads(Path("data/geo/coordenadas.json").read_text(encoding="utf-8"))
            for pid, k in known.items():
                if not pid.startswith("MAD:") or k.get("lat") is None:
                    continue
                p = session.get(Pharmacy, pid)
                if p:
                    p.lat, p.lon = k["lat"], k["lon"]
                    p.geo_precision = k.get("precision")
                    p.geo_source = "test_injected"

    return eng


@pytest.fixture(scope="session")
def session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_session(session_factory) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(session_factory) -> Generator[TestClient, None, None]:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

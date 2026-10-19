"""Genera app/test/fixtures/paridad_api.json: respuestas de la API sobre data/guardias.db.

El test de Flutter test/paridad_test.dart hace las mismas consultas al motor de la app (sobre
assets/snapshot.json, exportada de la misma base de datos) y comprueba que coinciden: farmacias de
guardia, mensaje y presencia de aviso. Regenerar después de exportar la instantánea:

    python scripts/generar_paridad.py
"""
from __future__ import annotations

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.api import app  # noqa: E402
from backend.db import create_db_engine, get_db  # noqa: E402

OUT = os.path.join(BASE_DIR, "app", "test", "fixtures", "paridad_api.json")

LUGARES = {
    "Palma": (39.5696, 2.6502),
    "Eivissa": (38.9067, 1.4206),
    "Cala Millor": (39.6052, 3.3862),
    "Murcia": (37.9922, -1.1307),
    "Cartagena": (37.6257, -0.9966),
    "Mula": (38.0413, -1.4904),
    "Yecla": (38.6136, -1.1146),
    "Pamplona": (42.8169, -1.6432),
    "Tudela": (42.0617, -1.6046),
    "Madrid Sol": (40.4169, -3.7035),
    "Getafe": (40.3083, -3.7327),
    "Pozuelo": (40.4357, -3.8130),
    "Zaragoza Pilar": (41.6488, -0.8891),
    "Zaragoza Actur": (41.6700, -0.9050),
    "Burgos": (42.3439, -3.6969),
}
FECHAS = ["2026-01-15", "2026-03-15", "2026-08-15", "2026-10-10", "2026-10-19", "2026-10-25", "2026-12-31", "2027-02-01"]
INSTANTES = ["2026-01-01T23:00:00+01:00", "2026-10-19T12:00:00+02:00", "2026-10-25T02:30:00+01:00"]


def main() -> int:
    engine = create_db_engine(f"sqlite:///{os.path.join(BASE_DIR, 'data', 'guardias.db')}")
    factory = sessionmaker(bind=engine)

    def override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    casos = []
    with TestClient(app) as client:
        for nombre, (lat, lon) in LUGARES.items():
            for fecha in FECHAS:
                r = client.get("/v1/guardias/dia", params={"lat": lat, "lon": lon, "fecha": fecha, "limit": 10000}).json()
                casos.append({"lugar": nombre, "lat": lat, "lon": lon, "fecha": fecha, **_resumen(r)})
            for at in INSTANTES:
                r = client.get("/v1/guardias", params={"lat": lat, "lon": lon, "at": at, "limit": 10000}).json()
                casos.append({"lugar": nombre, "lat": lat, "lon": lon, "instante": at, **_resumen(r)})
    app.dependency_overrides.clear()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(casos, fh, ensure_ascii=False, indent=1)
    print(f"{len(casos)} casos -> {OUT}")
    return 0


def _resumen(r: dict) -> dict:
    return {
        "cobertura": r["cobertura"],
        "mensaje": r["mensaje"],
        "aviso": r.get("aviso") is not None,
        "farmacias": sorted({g["farmacia"]["id"] for g in r["guardias"]}),
        # Turno elegido para cada farmacia (una farmacia en varios cuadrantes se muestra una vez).
        "turnos": sorted(f'{g["farmacia"]["id"]}|{g["turno"]["inicio"]}|{g["turno"]["fin"]}' for g in r["guardias"]),
    }


if __name__ == "__main__":
    raise SystemExit(main())

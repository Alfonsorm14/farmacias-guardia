"""Contrato real de importación probado con las cuatro fuentes inventadas."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.importer import import_source_data
from backend.models import Base, Pharmacy, Shift, Source
from ingesta.export import to_json
from ingesta.parsers.generico import parse_file

FIXTURES = Path(__file__).resolve().parents[2] / "tests/fixtures/generico"


@pytest.mark.parametrize("kind,filename,expected", [
    ("xlsx", "filas.xlsx", 3),
    ("csv", "franjas.csv", 2),
    ("ods", "calendario.ods", 3),
    ("pdf", "tabla.pdf", 2),
])
def test_generic_output_imports_idempotently_without_importer_changes(tmp_path, kind, filename, expected):
    # La API del parser permite revisar también las filas válidas de entradas con avisos.
    # El CLI impide publicar esas salidas hasta resolver las incidencias.
    result = parse_file(FIXTURES / filename, FIXTURES / f"{kind}.yaml")
    output = tmp_path / "inventado.json"
    output.write_text(json.dumps(to_json(result), ensure_ascii=False), encoding="utf-8")
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        for _ in range(2):
            summary = import_source_data(output, session_factory=factory, reuse_coordinates=False)
            assert summary["shifts"] == expected
        with factory() as session:
            pharmacies = session.scalars(select(Pharmacy)).all()
            shifts = session.scalars(select(Shift)).all()
            assert len(pharmacies) == len(result.pharmacies)
            assert len(shifts) == expected
            assert len(session.scalars(select(Source)).all()) == 1
            assert all(p.lat is None and p.lon is None for p in pharmacies)
            assert all(s.pharmacy_id in result.pharmacies for s in shifts)
    finally:
        engine.dispose()

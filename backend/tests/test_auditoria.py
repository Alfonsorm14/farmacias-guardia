"""Auditoría: integridad de importación, publicación y entradas de API."""
import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.api import app
from backend.db import create_db_engine, init_db
from backend.importer import import_source_data
from backend.models import Pharmacy, Shift


@pytest.fixture
def imported(tmp_path):
    engine = create_db_engine(f'sqlite:///{tmp_path / "audit.db"}')
    init_db(engine)
    factory = sessionmaker(bind=engine)
    data = json.loads(Path('data/out/zaragoza_2026.json').read_text())
    path = tmp_path / 'source.json'
    path.write_text(json.dumps(data))
    import_source_data(path, factory, reuse_coordinates=False)
    yield factory, path, data, tmp_path / 'audit.db'
    engine.dispose()


@pytest.mark.parametrize('mutation', ['empty', 'missing', 'orphan', 'naive', 'reversed', 'foreign'])
def test_importacion_rechazada_preserva_base(imported, mutation):
    factory, path, data, _ = imported
    broken = copy.deepcopy(data)
    if mutation == 'empty':
        broken['shifts'] = []
    elif mutation == 'missing':
        del broken['shifts']
    elif mutation == 'orphan':
        broken['shifts'][0]['pharmacy_id'] = 'INEXISTENTE'
    elif mutation == 'naive':
        broken['shifts'][0]['start'] = '2026-10-25T02:30:00'
    elif mutation == 'reversed':
        broken['shifts'][0]['end'] = broken['shifts'][0]['start']
    else:
        broken['source']['source_id'] = 'OTRA-FUENTE'
    with factory() as session:
        before = session.scalar(select(func.count()).select_from(Shift))
    path.write_text(json.dumps(broken))
    with pytest.raises(ValueError):
        import_source_data(path, factory, reuse_coordinates=False)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Shift)) == before
        assert {p.source_id for p in session.scalars(select(Pharmacy))} == {data['source']['source_id']}


@pytest.mark.parametrize('route', ['/v1/guardias', '/v1/guardias/dia'])
@pytest.mark.parametrize('extra', [{'lat': 'nan'}, {'lon': 'inf'}, {'lat': '91'}, {'lon': '-181'},
                                  {'radius_km': '-1'}, {'radius_km': 'nan'}, {'limit': '0'}, {'limit': '10001'}])
def test_api_rechaza_entradas_antes_de_consultar(route, extra):
    with TestClient(app) as client:
        response = client.get(route, params={'lat': 40, 'lon': -3, 'fecha': '2026-10-25', **extra})
    assert response.status_code == 422


@pytest.mark.parametrize('at', ['2026-10-25T02:30:00', '2027-03-28T02:30:00', '9999-12-31T23:59:59-12:00'])
def test_instante_ambiguo_inexistente_o_desbordado(at):
    from backend.api import _parse_at
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _parse_at(at)
    assert exc.value.status_code == 400


@pytest.mark.parametrize('category, kind', [('amenity', 'restaurant'), ('shop', 'chemist')])
def test_osm_no_confunde_comercio_con_farmacia(category, kind):
    from backend.geocode import _osm_pharmacy
    from backend.tests.test_geocode import _GeoStub, _osm
    pharmacy = Pharmacy(id='IB:x', region='04', holder='TINOCO GIL',
                        address='AV GABRIEL ALOMAR, 27', locality=None)
    candidate = _osm('Avinguda de Gabriel Alomar', '27', name='Tinoco')
    candidate.update({'class': category, 'type': kind})
    assert _osm_pharmacy(_GeoStub([candidate], []), pharmacy, center=(39.57, 2.65)) is None


@pytest.mark.parametrize('day, hours', [('2026-10-25', 25), ('2027-03-28', 23), ('2026-12-31', 24)])
def test_api_dia_natural_cambia_offset(monkeypatch, day, hours):
    import backend.api as api
    def capture(db, lat, lon, start, end, radius, limit):
        assert (end - start).total_seconds() == hours * 3600
        return {'guardias': []}
    monkeypatch.setattr(api, '_query_guardias', capture)
    assert api.get_guardias_dia(lat=40, lon=-3, fecha=day, radius_km=25, limit=500, db=None) == {'guardias': []}


def test_hora_repetida_con_offset_son_dos_instantes():
    from backend.api import _parse_at
    first = _parse_at('2026-10-25T02:30:00+02:00')
    second = _parse_at('2026-10-25T02:30:00+01:00')
    assert (second - first).total_seconds() == 3600

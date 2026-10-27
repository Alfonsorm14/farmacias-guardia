"""Fixture sintético compartido por API, motor snapshot y repositorio Flutter."""
import datetime as dt
import json
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from backend.api import _query_guardias
from backend.db import create_db_engine, init_db
from backend.models import Pharmacy, Shift, Source

FIXTURE = json.loads(Path('app/test/fixtures/paridad_elegibilidad.json').read_text())


@pytest.fixture
def parity_db(tmp_path):
    engine = create_db_engine(f'sqlite:///{tmp_path / "parity.db"}')
    init_db(engine)
    factory = sessionmaker(bind=engine)
    data = FIXTURE['snapshot']
    with factory() as session, session.begin():
        session.add(Source(source_id='TEST', publisher='Fuente de prueba', url='https://example.org',
                           license='Prueba', retrieved_at=dt.datetime(2026, 10, 27, tzinfo=dt.timezone.utc)))
        for i, p in enumerate(data['pharmacies']):
            zones = sorted({data['zones'][s[1]] for s in data['shifts'] if s[0] == i})
            session.add(Pharmacy(id=p[0], holder=p[1], region='13', address=p[2], locality=p[3],
                                 phone=p[4], lat=p[6], lon=p[7], source_id='TEST', zones=json.dumps(zones)))
        session.flush()
        for r in data['shifts']:
            session.add(Shift(pharmacy_id=data['pharmacies'][r[0]][0], zone=data['zones'][r[1]],
                              start_utc=dt.datetime.fromtimestamp(r[2]*60, dt.timezone.utc),
                              end_utc=dt.datetime.fromtimestamp(r[3]*60, dt.timezone.utc),
                              kind={'d':'diurna','n':'nocturna'}[r[4]], times_exact=bool(r[5]),
                              source_id='TEST', raw_label='Prueba'))
    with factory() as session:
        yield session
    engine.dispose()


@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda c:c['name'])
def test_api_paridad_elegibilidad(parity_db, case):
    from backend.api import MADRID_TZ
    day = 'fecha' in case
    start = dt.datetime.fromisoformat(case.get('fecha', case.get('at')))
    if day:
        start = start.replace(tzinfo=MADRID_TZ)
    end = start + dt.timedelta(days=1) if day else start
    result = _query_guardias(parity_db, 40, -3, start.astimezone(dt.timezone.utc),
                             end.astimezone(dt.timezone.utc), 25, 500)
    expected = case['response']
    assert [g['farmacia']['id'] for g in result['guardias']] == [g['farmacia']['id'] for g in expected['guardias']]
    assert result['farmacias_sin_coordenadas'] == expected['farmacias_sin_coordenadas']
    assert result.get('proximo_cambio') == expected['proximo_cambio']
    assert result['mensaje'] == expected['mensaje']
    assert result['datos_hasta'] == expected['datos_hasta']


def test_limite_del_generador_de_paridad_compatible(client):
    """El generador existente pide 10000 resultados; no debe recibir un 422."""
    response = client.get('/v1/guardias', params={'lat':40, 'lon':-3, 'limit':10000,
                                               'at':'2026-10-27T10:30:00+01:00'})
    assert response.status_code == 200

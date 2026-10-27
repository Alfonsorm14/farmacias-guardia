"""Conservación e integridad de la exportación: solo SQLite y destinos temporales."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.export_snapshot import export


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'source.db'
    with sqlite3.connect(path) as conn:
        # Sin constraints para simular también una base dañada o un esquema antiguo.
        conn.executescript('''
            CREATE TABLE sources (source_id TEXT, publisher TEXT, url TEXT, license TEXT, retrieved_at TEXT);
            CREATE TABLE pharmacies (id TEXT, holder TEXT, address TEXT, locality TEXT, phone TEXT,
                duty_phone TEXT, lat REAL, lon REAL, geo_precision TEXT, source_id TEXT);
            CREATE TABLE shifts (id INTEGER, pharmacy_id TEXT, source_id TEXT, zone TEXT,
                start_utc TEXT, end_utc TEXT, kind TEXT, times_exact INTEGER);
            INSERT INTO sources VALUES ('TEST', 'Prueba', 'https://example.org', 'Prueba', '2026-10-27 08:00:00');
            INSERT INTO pharmacies VALUES ('TEST:1', 'Farmacia', 'Calle 1', 'Localidad', NULL,
                NULL, 40, -3, 'portal', 'TEST');
            INSERT INTO shifts VALUES (1, 'TEST:1', 'TEST', 'ZONA',
                '2026-10-27 09:00:00', '2026-10-27 10:00:00', 'diurna', 1);
        ''')
    return path


def test_exporta_referencias_e_indices_consistentes(database, tmp_path):
    target = tmp_path / 'snapshot.json'
    assert export(str(database), str(target)) == {'farmacias':1, 'turnos':1, 'zonas':1}
    data = json.loads(target.read_text())
    pindex, zindex, start, end, kind, exact = data['shifts'][0]
    assert data['pharmacies'][pindex][0] == 'TEST:1'
    assert data['sources'][data['pharmacies'][pindex][9]][0] == 'TEST'
    assert data['zones'][zindex] == 'ZONA'
    assert end - start == 60
    assert (kind, exact) == ('d', 1)


@pytest.mark.parametrize('mutation', [
    'DELETE FROM sources', 'DELETE FROM pharmacies', 'DELETE FROM shifts',
    'INSERT INTO sources SELECT * FROM sources', 'INSERT INTO pharmacies SELECT * FROM pharmacies',
    'INSERT INTO shifts SELECT * FROM shifts',
    "UPDATE pharmacies SET source_id='INEXISTENTE'", "UPDATE shifts SET source_id='INEXISTENTE'",
    "UPDATE shifts SET pharmacy_id='INEXISTENTE'", "UPDATE shifts SET end_utc=start_utc",
    "UPDATE shifts SET end_utc='2026-10-27 08:00:00'",
    "UPDATE shifts SET end_utc='2026-10-27 09:00:30'",
    "UPDATE shifts SET start_utc='fecha corrupta'", "UPDATE shifts SET zone=''",
    "UPDATE shifts SET kind='desconocido'", "UPDATE shifts SET times_exact=2",
    "INSERT INTO sources SELECT 'OTRA', publisher, url, license, retrieved_at FROM sources; UPDATE shifts SET source_id='OTRA'",
])
def test_validacion_no_toca_snapshot_anterior(database, tmp_path, mutation):
    with sqlite3.connect(database) as conn:
        conn.executescript(mutation)
    target = tmp_path / 'snapshot.json'
    previous = b'copia anterior exacta\n'
    target.write_bytes(previous)
    with patch('scripts.export_snapshot.tempfile.NamedTemporaryFile') as temporary:
        with pytest.raises(ValueError):
            export(str(database), str(target))
        temporary.assert_not_called()
    assert target.read_bytes() == previous
    assert sorted(p.name for p in tmp_path.iterdir()) == ['snapshot.json', 'source.db']


@pytest.mark.parametrize('stage', ['json', 'fsync', 'replace'])
def test_fallo_de_escritura_preserva_snapshot_y_limpia_temporal(database, tmp_path, stage):
    target = tmp_path / 'snapshot.json'
    target.write_bytes(b'copia anterior')
    def partial(data, fh, **kwargs):
        fh.write('parcial')
        raise OSError('fallo de escritura simulado')
    name = {'json':'json.dump', 'fsync':'os.fsync', 'replace':'os.replace'}[stage]
    with patch('scripts.export_snapshot.'+name, side_effect=partial if stage == 'json' else OSError('fallo simulado')):
        with pytest.raises(OSError):
            export(str(database), str(target))
    assert target.read_bytes() == b'copia anterior'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['snapshot.json', 'source.db']


def test_cli_base_vacia_sale_con_error_sin_tocar_destino(database, tmp_path):
    with sqlite3.connect(database) as conn:
        conn.execute('DELETE FROM shifts')
    target = tmp_path / 'snapshot.json'
    target.write_bytes(b'copia anterior')
    result = subprocess.run([sys.executable, 'scripts/export_snapshot.py', '--db', str(database),
                             '--out', str(target)], capture_output=True, text=True)
    assert result.returncode != 0
    assert target.read_bytes() == b'copia anterior'


def test_base_inexistente_no_crea_archivo_ni_toca_destino(tmp_path):
    target = tmp_path / 'snapshot.json'
    target.write_bytes(b'copia anterior')
    database = tmp_path / 'missing.db'
    with pytest.raises(sqlite3.OperationalError):
        export(str(database), str(target))
    assert not database.exists()
    assert target.read_bytes() == b'copia anterior'

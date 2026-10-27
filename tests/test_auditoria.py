"""Regresiones de horarios y filas incompletas, sin red."""
import csv
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from ingesta.parsers.madrid import CSV_COLUMNS, _parse_csv, _shift_times
from ingesta.parsers.navarra import _parse_records
from ingesta.parsers.zaragoza import _times


class HorariosAuditoriaTests(unittest.TestCase):
    def navarra(self, start, end):
        warnings = []
        _, shifts = _parse_records([[1, '25/10/2026', start, end, 'Pamplona', 'Zona',
                                     'Calle 1', 'Titular', 'F1', '948123456']], 'fixture.json', warnings)
        return list(shifts.values()), warnings

    def test_navarra_no_trunca_minutos(self):
        shifts, warnings = self.navarra('09:30', '22:15')
        self.assertEqual(warnings, [])
        self.assertEqual((shifts[0].start.hour, shifts[0].start.minute), (9, 30))
        self.assertEqual((shifts[0].end.hour, shifts[0].end.minute), (22, 15))

    def test_navarra_24_es_medianoche_siguiente(self):
        shifts, warnings = self.navarra('24', '8')
        self.assertEqual(warnings, [])
        self.assertEqual(shifts[0].start.date(), date(2026, 10, 26))
        self.assertEqual(shifts[0].end.date(), date(2026, 10, 26))
        self.assertEqual(shifts[0].kind, "diurna")
        self.assertEqual((shifts[0].end - shifts[0].start).total_seconds(), 8 * 3600)

    def test_navarra_minuto_invalido_se_omite(self):
        shifts, warnings = self.navarra('09:99', '22')
        self.assertEqual(shifts, [])
        self.assertIn('HORARIO_INVALIDO', warnings[0])

    def test_madrid_no_convierte_25_en_1(self):
        self.assertIsNone(_shift_times(date(2026, 10, 25), 'SERVICIO DIURNO (25:00-08:00 H)'))

    def test_zaragoza_no_convierte_25_en_1(self):
        with self.assertRaises(ValueError):
            _times(date(2026, 10, 25), '25 h a 8 h')

    def test_csv_incompleto_no_interrumpe_otras_filas(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'madrid_2026.csv'
            with path.open('w', encoding='utf-8-sig', newline='') as fh:
                writer = csv.writer(fh, delimiter=';')
                writer.writerow(CSV_COLUMNS)
                writer.writerow(['MADRID', 'CENTRO', '25/10/2026', '46'])
                writer.writerow(['MADRID', 'CENTRO', '25/10/2026', '47', 'Calle 2',
                                 'SERVICIO DIURNO (09:30-23:00 H)', '913123456'])
            warnings = []
            pharmacies, shifts = _parse_csv(str(path), warnings, date(2026, 10, 27))
            self.assertEqual(set(pharmacies), {'MAD:47'})
            self.assertEqual(len(shifts), 1)
            self.assertIn('FILA_INCOMPLETA', warnings[0])

    def test_cambio_hora_y_fin_anio(self):
        for day, hours in [(date(2026, 10, 25), 25), (date(2027, 3, 28), 23), (date(2026, 12, 31), 24)]:
            with self.subTest(day=day):
                start, end, _, _ = _shift_times(day, 'SERVICIO 24 HORAS (00:00-00:00 H DÍA SIGUIENTE)')
                self.assertEqual((end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds(), hours * 3600)

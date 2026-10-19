"""Tests del parser de Navarra (datos abiertos) y de la capa IDENA."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingesta.common import TZ
from ingesta.parsers.navarra import load_idena, parse_dir, utm30n_to_wgs84

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "navarra")
DBF = os.path.join(RAW_DIR, "idena", "DOTACI_Sym_Farmacias.dbf")


def _record(rid, fecha, desde, hasta, cod="F00001", tel="948 000000"):
    return [rid, fecha, desde, hasta, "Pamplona / Iruña", "Pamplona y comarca/Iruñerria",
            "C/ Prueba, 1", "Prueba Prueba, Ana", cod, tel]


class NavarraTests(unittest.TestCase):
    def test_tipos_y_horas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = {"fields": [], "records": [
                _record(1, "12/10/2026", "9", "9"),
                _record(2, "12/10/2026", "21", "10", cod="F00002"),
                _record(3, "12/10/2026", "10", "21", cod="F00003"),
            ]}
            with open(os.path.join(tmp, "farmacias_guardia_20261012.json"), "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            result = parse_dir(tmp)
        by_id = {s.pharmacy_id: s for s in result.shifts}
        s24 = by_id["NA:F00001"]
        self.assertEqual(s24.kind, "24h")
        self.assertEqual(s24.start, datetime(2026, 10, 12, 9, tzinfo=TZ))
        self.assertEqual(s24.end, datetime(2026, 10, 13, 9, tzinfo=TZ))
        noct = by_id["NA:F00002"]
        self.assertEqual(noct.kind, "nocturna")
        self.assertEqual(noct.end, datetime(2026, 10, 13, 10, tzinfo=TZ))
        self.assertEqual(by_id["NA:F00003"].kind, "diurna")
        self.assertEqual(result.pharmacies["NA:F00001"].phone, "948000000")
        self.assertEqual(result.source.license, "CC BY 4.0")

    def test_descarga_mas_reciente_manda(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for name, hasta in (("20261012", "21"), ("20261013", "22")):
                with open(os.path.join(tmp, f"farmacias_guardia_{name}.json"), "w", encoding="utf-8") as fh:
                    json.dump({"records": [_record(1, "14/10/2026", "9", hasta)]}, fh)
            result = parse_dir(tmp)
        self.assertEqual(len(result.shifts), 1)
        self.assertEqual(result.shifts[0].end.hour, 22)

    def test_datos_reales(self) -> None:
        result = parse_dir(RAW_DIR)
        self.assertGreater(len(result.pharmacies), 80)
        self.assertEqual(result.warnings, [])
        for shift in result.shifts:
            self.assertGreater(shift.end, shift.start)
            self.assertTrue(shift.pharmacy_id.startswith("NA:F"))

    def test_utm_a_wgs84(self) -> None:
        lat, lon = utm30n_to_wgs84(500000.0, 4650000.0)
        self.assertAlmostEqual(lon, -3.0, places=6)
        self.assertAlmostEqual(lat, 42.0, delta=0.05)

    def test_idena(self) -> None:
        coords = load_idena(DBF)
        self.assertGreater(len(coords), 500)
        lat, lon = coords["F00001"]  # Pamplona, calle Chapitela
        self.assertAlmostEqual(lat, 42.818, delta=0.01)
        self.assertAlmostEqual(lon, -1.643, delta=0.01)


if __name__ == "__main__":
    unittest.main()

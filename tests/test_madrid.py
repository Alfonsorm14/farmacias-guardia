"""Tests del parser de la ciudad de Madrid (datos.madrid.es)."""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingesta.common import TZ
from ingesta.parsers.madrid import _shift_times, parse_dir, parse_line

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "madrid")


class MadridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = parse_dir(RAW_DIR)

    def test_linea(self) -> None:
        row = parse_line(
            "MADRID      CENTRO                    01/10/2026 46         PZ DEL ANGEL, 14"
            "                                     SERVICIO 24 HORAS (09:30-09:30 H DÍA SIGUIENTE)   913692318"
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["numero"], "46")
        self.assertEqual(row["direccion"], "PZ DEL ANGEL, 14")
        self.assertEqual(row["telefono"], "913692318")

    def test_horarios(self) -> None:
        start, end, kind, _ = _shift_times(date(2026, 10, 1), "SERVICIO 24 HORAS (09:30-09:30 H DÍA SIGUIENTE)")
        self.assertEqual((start, end, kind), (
            datetime(2026, 10, 1, 9, 30, tzinfo=TZ), datetime(2026, 10, 2, 9, 30, tzinfo=TZ), "24h"))
        start, end, kind, _ = _shift_times(date(2026, 10, 1), "SERVICIO DIURNO (07:00-23:00 H)")
        self.assertEqual((start.hour, end.hour, end.day, kind), (7, 23, 1, "diurna"))

    def test_octubre_2026(self) -> None:
        self.assertEqual(self.result.warnings, [])
        days = {s.start.date() for s in self.result.shifts}
        self.assertEqual(len([d for d in days if d.month == 10 and d.year == 2026]), 31)
        self.assertGreater(len(self.result.pharmacies), 70)
        dia1 = [s for s in self.result.shifts if s.start.date() == date(2026, 10, 1) and s.pharmacy_id == "MAD:46"]
        self.assertEqual(len(dia1), 1)
        self.assertEqual(dia1[0].kind, "24h")
        self.assertEqual(self.result.pharmacies["MAD:46"].address, "PZ DEL ANGEL, 14")
        self.assertEqual(self.result.source.license, "CC BY 4.0")


if __name__ == "__main__":
    unittest.main()

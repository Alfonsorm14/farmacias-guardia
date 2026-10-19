"""Tests del parser de la ciudad de Madrid (datos.madrid.es)."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
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

    def test_pdf_y_csv_coinciden_en_octubre(self) -> None:
        """El CSV anual y el PDF de octubre dan los mismos turnos (sin avisos PDF_CSV_DIFIEREN)."""
        octubre = [s for s in self.result.shifts if (s.start.year, s.start.month) == (2026, 10)]
        self.assertEqual(len(octubre), 2199)  # el CSV trae 13 filas duplicadas que se cuentan una vez


class MadridCsvTests(unittest.TestCase):
    CAB = "\ufeffMunicipio;Barrio;Fecha;Farmacia;Dirección;Duración;Teléfono\r\n"

    def _dir(self, csv_text: str, con_pdf: bool) -> str:
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        with open(os.path.join(d, "madrid_2026.csv"), "w", encoding="utf-8", newline="") as fh:
            fh.write(csv_text)
        if con_pdf:
            shutil.copy(os.path.join(RAW_DIR, "madrid_2026-10.pdf"), d)
        return d

    def test_csv_solo_dos_ultimos_meses_y_duplicados(self) -> None:
        filas = (
            "MADRID;CENTRO;15/08/2026;46;PZ DEL ANGEL,  14;SERVICIO 24 HORAS (09:30-09:30 H DÍA SIGUIENTE);913690000\r\n"
            "MADRID;CENTRO;15/09/2026;46;PZ DEL ANGEL,  14;SERVICIO 24 HORAS (09:30-09:30 H DÍA SIGUIENTE);913690000\r\n"
            "MADRID;CENTRO;15/11/2026;46;PZ DEL ANGEL,  14;SERVICIO DIURNO (09:30-23:00 H);913690000\r\n"
            "MADRID;CENTRO;15/11/2026;46;PZ DEL ANGEL,  14;SERVICIO DIURNO (09:30-23:00 H);913690000\r\n"
        )
        r = parse_dir(self._dir(self.CAB + filas, con_pdf=False))
        self.assertEqual(r.warnings, [])
        dias = sorted(s.start.date() for s in r.shifts)
        self.assertEqual(dias, [date(2026, 9, 15), date(2026, 11, 15)])  # agosto fuera, duplicado una vez
        self.assertEqual(r.pharmacies["MAD:46"].address, "PZ DEL ANGEL, 14")

    def test_aviso_si_pdf_y_csv_no_coinciden(self) -> None:
        filas = "MADRID;CENTRO;01/10/2026;99999;CL FALSA, 1;SERVICIO DIURNO (09:30-23:00 H);910000000\r\n"
        r = parse_dir(self._dir(self.CAB + filas, con_pdf=True))
        self.assertTrue(any(w.startswith("PDF_CSV_DIFIEREN 01/10/2026") for w in r.warnings), r.warnings)

    def test_columnas_inesperadas(self) -> None:
        r = parse_dir(self._dir("Fecha;Farmacia\r\n01/10/2026;1\r\n", con_pdf=False))
        self.assertTrue(r.warnings and "COLUMNAS_INESPERADAS" in r.warnings[0])


if __name__ == "__main__":
    unittest.main()

"""Tests del parser de Murcia (BORM 2025-6468, plan de urgencias 2026).

Incluye pruebas sobre el PDF real (sin mocks) y casos sintéticos de las
utilidades de reconstrucción del Anexo II.
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingesta.parsers.murcia import (
    SOURCE_ID,
    URL,
    _anexo2_page_range,
    _anexo2_vocabulary,
    _column_of,
    _join_fragment,
    parse,
)
from ingesta.common import normalize, pdf_bbox_pages

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_PATH = os.path.join(
    BASE_DIR, "data", "raw", "murcia", "2026", "BORM_2025_6468.pdf"
)


def _zone(name: str, number: int) -> bool:
    return bool(re.fullmatch(rf"AGRUPACION {number} \([^)]*\)( - .*)?", name))


class MurciaAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = parse(PDF_PATH)

    def test_source_info(self) -> None:
        self.assertEqual(self.result.source.source_id, SOURCE_ID)
        self.assertEqual(self.result.source.url, URL)
        self.assertIn("Murcia", self.result.source.publisher)

    def test_mu45_directorio(self) -> None:
        pharmacy = self.result.pharmacies["MU:45"]
        self.assertEqual(pharmacy.holder, "RUBIO FERNANDEZ, MARIA")
        self.assertEqual(pharmacy.phone, "968802950")
        self.assertEqual(pharmacy.address, "CL. MAYOR, 87")
        self.assertEqual(pharmacy.locality, "ALCANTARILLA")
        self.assertEqual(pharmacy.postal_code, "30820")

    def test_mu534_direccion(self) -> None:
        pharmacy = self.result.pharmacies["MU:534"]
        self.assertEqual(
            pharmacy.address,
            "CALLE MEDICO PEDRO NOGUEROLES, ESQUINA CALLE ANDORRA",
        )

    def test_agrupacion1_enero(self) -> None:
        por_dia = {}
        for shift in self.result.shifts:
            if _zone(shift.zone, 1):
                por_dia.setdefault(shift.start.date(), set()).add(
                    shift.pharmacy_id
                )
        self.assertIn("MU:431", por_dia[date(2026, 1, 1)])
        self.assertIn("MU:46", por_dia[date(2026, 1, 3)])

    def test_agrupacion6_ocho_farmacias_24h(self) -> None:
        esperadas = {
            "MU:12",
            "MU:94",
            "MU:178",
            "MU:180",
            "MU:257",
            "MU:312",
            "MU:376",
            "MU:393",
        }
        agr6 = [
            s
            for s in self.result.shifts
            if _zone(s.zone, 6) and s.kind == "24h"
        ]
        self.assertEqual({s.pharmacy_id for s in agr6}, esperadas)
        for pharmacy_id in esperadas:
            self.assertEqual(
                sum(1 for s in agr6 if s.pharmacy_id == pharmacy_id),
                365,
                msg=pharmacy_id,
            )

    def test_agrupacion2_mu56_y_refuerzo_no_soportado(self) -> None:
        shifts56 = [
            s
            for s in self.result.shifts
            if s.pharmacy_id == "MU:56" and s.kind == "24h"
        ]
        self.assertEqual(len(shifts56), 365)

        refuerzos = [
            s
            for s in self.result.shifts
            if _zone(s.zone, 2) and s.kind == "refuerzo"
        ]
        self.assertEqual(refuerzos, [])

        avisos = [
            w
            for w in self.result.warnings
            if "REFUERZO_REGLA_NO_SOPORTADA" in w and "AGRUPACION 2:" in w
        ]
        self.assertEqual(len(avisos), 1)
        self.assertIn("lunes a s", avisos[0])

    def test_todos_los_turnos_referencian_farmacia(self) -> None:
        faltan = [
            s
            for s in self.result.shifts
            if s.pharmacy_id not in self.result.pharmacies
        ]
        self.assertEqual(faltan, [])

    def test_times_exact_por_tipo(self) -> None:
        for shift in self.result.shifts:
            if shift.kind == "refuerzo":
                self.assertTrue(shift.times_exact)
            else:
                self.assertFalse(shift.times_exact)

    def test_localidades_reconstruidas(self) -> None:
        localities = {
            pharmacy.id: pharmacy.locality
            for pharmacy in self.result.pharmacies.values()
        }
        malformed = ("LOSALCAZARES", "TORREPACHECO", "DESEGURA", "DECOTILLAS", "ALMENDRIC OS")
        found = [
            f"{pharmacy_id}: {locality}"
            for pharmacy_id, locality in localities.items()
            if locality and any(token in locality for token in malformed)
        ]
        self.assertEqual(found, [])
        self.assertEqual(localities["MU:460"], "LOS NAREJOS (LOS ALCAZARES)")
        self.assertTrue(localities["MU:66"].startswith("DOLORES"))
        self.assertIn("TORRE PACHECO", localities["MU:66"])

    def test_tokens_localidad_pertenecen_al_vocabulario(self) -> None:
        pages = pdf_bbox_pages(PDF_PATH)
        assert pages is not None
        span = _anexo2_page_range(pages)
        assert span is not None
        vocabulary = _anexo2_vocabulary(pages, *span)
        short_words = {"DE", "LA", "LOS", "EL", "LAS", "DEL"}
        unknown = sorted(
            {
                token
                for pharmacy in self.result.pharmacies.values()
                for token in re.findall(r"[^\W\d_]+", pharmacy.locality or "")
                if normalize(token) not in vocabulary
                and normalize(token) not in short_words
            }
        )
        self.assertEqual(unknown, [])


class ReconstruccionColumnasTests(unittest.TestCase):
    def test_join_fragment(self) -> None:
        self.assertEqual(_join_fragment("", "MURCIA"), "MURCIA")
        self.assertEqual(_join_fragment("ALCANTARIL", "LA"), "ALCANTARILLA")
        self.assertEqual(
            _join_fragment("ALHAMA DE", "MURCIA"), "ALHAMA DE MURCIA"
        )
        self.assertEqual(
            _join_fragment("SANGONERA", "LA SECA"), "SANGONERA LA SECA"
        )
        self.assertEqual(
            _join_fragment("SAN JOSE DE", "LA VEGA"), "SAN JOSE DE LA VEGA"
        )
        self.assertEqual(
            _join_fragment("SANCHEZ-", "CARRASCOSA"), "SANCHEZ-CARRASCOSA"
        )
        self.assertEqual(
            _join_fragment("CALABARDIN", "A (AGUILAS)"),
            "CALABARDINA (AGUILAS)",
        )
        self.assertEqual(
            _join_fragment("MIRANDA(CA", "RTAGENA)"), "MIRANDA(CARTAGENA)"
        )
        self.assertEqual(_join_fragment("JAVALI", "NUEVO"), "JAVALI NUEVO")
        self.assertEqual(
            _join_fragment("LOS NAREJOS (LOS", "ALCAZARES)"),
            "LOS NAREJOS (LOS ALCAZARES)",
        )

    def test_column_of(self) -> None:
        self.assertEqual(_column_of(86.6), 0)
        self.assertEqual(_column_of(122.9), 1)
        self.assertEqual(_column_of(231.2), 2)
        self.assertEqual(_column_of(260.2), 3)
        self.assertEqual(_column_of(318.0), 4)
        self.assertEqual(_column_of(419.2), 5)
        self.assertEqual(_column_of(484.2), 6)


if __name__ == "__main__":
    unittest.main()

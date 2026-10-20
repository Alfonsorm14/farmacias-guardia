"""Tests del parser de Baleares (CAIB 2026).

Incluye pruebas sobre los PDF reales (sin mocks) y casos sintéticos de líneas.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import date, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingesta.parsers.baleares import (
    _extract_locality,
    _page_column_x,
    _resolve_ambiguous,
    make_shift,
    normalize,
    parse_date_line,
    parse_dir,
    parse_pharmacy_line,
    parse_shift_header,
    pharmacy_id,
    split_holder_address,
)
from ingesta.export import to_json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "baleares", "2026")
V1_PATH = os.path.join(BASE_DIR, "data", "out", "baleares_2026_v1.json")


class BalearesAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = parse_dir(RAW_DIR)

    def test_26_pdfs_con_texto_y_uno_sin_texto(self) -> None:
        """Sant Antoni no tiene capa de texto: se usa su transcripción verificada."""
        pdfs = [f for f in os.listdir(RAW_DIR) if f.lower().endswith(".pdf")]
        self.assertEqual(len(pdfs), 27)
        sin_texto = [w for w in self.result.warnings if "SIN_TEXTO" in w]
        self.assertEqual(sin_texto, [])
        transcritos = [w for w in self.result.warnings if "TRANSCRIPCION" in w]
        self.assertEqual(len(transcritos), 1)
        self.assertIn("Sant_Antoni", transcritos[0])
        zones = {shift.zone for shift in self.result.shifts}
        self.assertEqual(len(zones), 27)

    def test_sant_antoni_transcripcion(self) -> None:
        shifts = [s for s in self.result.shifts if s.zone == "SANT ANTONI"]
        self.assertEqual(len({s.start.date() for s in shifts}), 365)
        dia1 = [s for s in shifts if s.start.date() == date(2026, 1, 1)]
        holders = {(s.kind, self.result.pharmacies[s.pharmacy_id].holder) for s in dia1}
        self.assertEqual(holders, {("diurna", "BRU BONILLA"), ("nocturna", "BRU BONILLA")})
        bru = self.result.pharmacies[dia1[0].pharmacy_id]
        self.assertEqual(bru.phone, "971724707")
        # El 9 de enero la fuente solo publica servicio diurno (cuatro farmacias).
        dia9 = [s for s in shifts if s.start.date() == date(2026, 1, 9)]
        self.assertEqual({s.kind for s in dia9}, {"diurna"})
        self.assertEqual(len(dia9), 4)
        farmacias = {
            p.phone for pid, p in self.result.pharmacies.items()
            if any(s.pharmacy_id == pid for s in shifts)
        }
        self.assertEqual(len(farmacias), 10)

    def test_palma_2026_01_01(self) -> None:
        day = date(2026, 1, 1)
        shifts = [
            s
            for s in self.result.shifts
            if s.zone == "PALMA" and s.start.date() == day
        ]
        diurnas = [s for s in shifts if s.kind == "diurna"]
        nocturnas = [s for s in shifts if s.kind == "nocturna"]

        self.assertEqual(len(diurnas), 19)
        for shift in diurnas:
            self.assertEqual(shift.start.time(), time(9, 0))
            self.assertEqual(shift.end.time(), time(22, 0))
            self.assertEqual(shift.end.date(), day)

        self.assertEqual(len(nocturnas), 3)
        for shift in nocturnas:
            self.assertEqual(shift.start.time(), time(22, 0))
            self.assertEqual(shift.end.time(), time(9, 0))
            self.assertEqual(shift.end.date(), date(2026, 1, 2))

    def test_formentera_2026_01_01(self) -> None:
        day = date(2026, 1, 1)
        shifts = [
            s
            for s in self.result.shifts
            if s.zone == "FORMENTERA" and s.start.date() == day
        ]
        self.assertEqual(len(shifts), 1)
        shift = shifts[0]
        self.assertEqual(shift.kind, "24h")
        self.assertEqual(shift.start.time(), time(9, 0))
        self.assertEqual(shift.end, shift.start.replace(day=2))

        pharmacy = self.result.pharmacies[shift.pharmacy_id]
        self.assertEqual(pharmacy.holder, "TORRES - TORRES")
        self.assertEqual(pharmacy.phone, "971322419")

    def _by_phone(self, phone: str):
        matches = [
            p for p in self.result.pharmacies.values() if p.phone == phone
        ]
        self.assertEqual(len(matches), 1, msg=phone)
        return matches[0]

    def test_sin_warnings_ambigua(self) -> None:
        ambiguous = [
            w for w in self.result.warnings if "LINEA_AMBIGUA" in w
        ]
        self.assertEqual(ambiguous, [])

    def test_riera_oliver_magdalena_columnas(self) -> None:
        pharmacy = self._by_phone("971649144")
        self.assertEqual(pharmacy.holder, "RIERA OLIVER, Mª MAGDALENA")
        self.assertEqual(pharmacy.address, "BATLE ANDREU BURGUERA MUT,9")
        self.assertEqual(pharmacy.locality, "SES SALINES")

    def test_sastre_barcelo_columnas(self) -> None:
        pharmacy = self._by_phone("971650662")
        self.assertEqual(pharmacy.holder, "SASTRE BARCELO, BARTOLOME")
        self.assertEqual(
            pharmacy.address, "CL DELS AMETLLERS, 25 - Local 1. CAMPOS"
        )
        self.assertIsNone(pharmacy.locality)

    def test_sagrista_farre_columnas(self) -> None:
        pharmacy = self._by_phone("971609946")
        self.assertEqual(pharmacy.holder, "SAGRISTA-FARRE-MATEMALAS")
        self.assertEqual(
            pharmacy.address, "C/SON RAPINYA, 31 LOC. 7,8 (Rotonda Colegios)"
        )
        self.assertIsNone(pharmacy.locality)

    def test_azcarate_hernandez_pinzon_columnas(self) -> None:
        pharmacy = self._by_phone("971839503")
        self.assertEqual(pharmacy.holder, "AZCARATE HERNANDEZ-PINZON")
        self.assertEqual(
            pharmacy.address,
            "GLOSADOR SEBASTIA VIDAL, sostre, 12-C'AS CONCOS",
        )
        self.assertIsNone(pharmacy.locality)

    @unittest.skipUnless(os.path.exists(V1_PATH), "copia local de la versión 1 (no está en git)")
    def test_ids_palma_2026_01_01_se_conservan(self) -> None:
        with open(V1_PATH, encoding="utf-8") as handle:
            v1 = json.load(handle)
        v1_pharmacies = {p["id"]: p for p in v1["pharmacies"]}

        v1_ids = {
            shift["pharmacy_id"]
            for shift in v1["shifts"]
            if shift["zone"] == "PALMA"
            and shift["start"][:10] == date(2026, 1, 1).isoformat()
        }
        current_ids = {
            shift.pharmacy_id
            for shift in self.result.shifts
            if shift.zone == "PALMA" and shift.start.date() == date(2026, 1, 1)
        }

        self.assertEqual(v1_ids, current_ids)

    def test_exporta_zonas_para_cada_farmacia(self) -> None:
        pharmacies = to_json(self.result)["pharmacies"]
        self.assertTrue(all(pharmacy["zones"] for pharmacy in pharmacies))
        alcover = next(
            pharmacy
            for pharmacy in pharmacies
            if pharmacy["holder"] == "ALCOVER CASASNOVAS, R"
        )
        self.assertIn("PALMA", alcover["zones"])

    def test_costa_amengual_duty_phone(self) -> None:
        matches = [
            p
            for p in self.result.pharmacies.values()
            if normalize(p.holder) == "COSTA AMENGUAL"
        ]
        self.assertEqual(len(matches), 1)
        pharmacy = matches[0]
        self.assertEqual(pharmacy.duty_phone, "678048796")
        self.assertEqual(pharmacy.phone, "971874291")
        self.assertEqual(pharmacy.locality, "SENCELLES")

    def test_ningun_turno_invertido(self) -> None:
        for shift in self.result.shifts:
            self.assertLess(shift.start, shift.end, msg=shift.raw_label)


class SyntheticLineTests(unittest.TestCase):
    def test_split_standard(self) -> None:
        line = "ALONSO GARCIA                     RECH, 5 - BINISSALEM"
        holder, address, ambiguous = split_holder_address(line)
        self.assertEqual(holder, "ALONSO GARCIA")
        self.assertEqual(address, "RECH, 5 - BINISSALEM")
        self.assertFalse(ambiguous)

    def test_split_ambiguo_conserva_linea_completa(self) -> None:
        line = (
            "SAGRISTA-FARRE-MATEMALAS C/SON RAPINYA, 31 LOC. 7,8 "
            "(Rotonda Colegios)"
        )
        holder, address, ambiguous = split_holder_address(line)
        self.assertTrue(ambiguous)
        self.assertEqual(holder, "SAGRISTA-FARRE-MATEMALAS")
        self.assertEqual(address, line)

    def test_duty_phone_extraido_y_quitado_de_direccion(self) -> None:
        line = (
            "COSTA AMENGUAL                    ANTONI MAURA, 1 - SENCELLES   "
            "( telf. guàrdies 678048796 )      971874291"
        )
        parsed = parse_pharmacy_line(line)
        assert parsed is not None
        pharmacy, ambiguous = parsed
        self.assertFalse(ambiguous)
        self.assertEqual(pharmacy.holder, "COSTA AMENGUAL")
        self.assertEqual(pharmacy.address, "ANTONI MAURA, 1")
        self.assertEqual(pharmacy.locality, "SENCELLES")
        self.assertEqual(pharmacy.phone, "971874291")
        self.assertEqual(pharmacy.duty_phone, "678048796")

    def test_locality_segun_patron(self) -> None:
        cases = [
            (
                "BATLE ANDREU BURGUERA MUT,9 - SES SALINES",
                "BATLE ANDREU BURGUERA MUT,9",
                "SES SALINES",
            ),
            (
                "AV. JOAN MIRÓ, 186 (davant C.Cial. Porto-Pí)-PALMA",
                "AV. JOAN MIRÓ, 186 (davant C.Cial. Porto-Pí)",
                "PALMA",
            ),
            (
                "CL GRAN VIA COLON, 177-181 - INCA",
                "CL GRAN VIA COLON, 177-181",
                "INCA",
            ),
            (
                "AV GABRIEL ALOMAR I VILLALONGA, 27",
                "AV GABRIEL ALOMAR I VILLALONGA, 27",
                None,
            ),
            (
                "C/SON RAPINYA, 31 LOC. 7,8 (Rotonda Colegios)",
                "C/SON RAPINYA, 31 LOC. 7,8 (Rotonda Colegios)",
                None,
            ),
            (
                "X - Frente Ed.Portals Plaza. PORTALS NOUS",
                "X",
                "PORTALS NOUS",
            ),
            (
                "X - CALA LLITERAS (CALA RATJADA",
                "X",
                "CALA LLITERAS (CALA RATJADA)",
            ),
            ("X - URB. MAIORIS", "X - URB. MAIORIS", None),
        ]
        for address, expected_address, expected_locality in cases:
            addr, locality = _extract_locality(address)
            self.assertEqual(addr, expected_address, msg=address)
            self.assertEqual(locality, expected_locality, msg=address)

    def test_locality_guion_pegado_es_direccion(self) -> None:
        address = "GLOSADOR SEBASTIA VIDAL, sostre, 12-C'AS CONCOS"
        self.assertEqual(
            _extract_locality(address, tight_hyphen_is_address=True),
            (address, None),
        )
        self.assertEqual(
            _extract_locality(
                "BATLE ANDREU BURGUERA MUT,9 - SES SALINES",
                tight_hyphen_is_address=True,
            ),
            ("BATLE ANDREU BURGUERA MUT,9", "SES SALINES"),
        )
        self.assertEqual(
            _extract_locality(address),
            ("GLOSADOR SEBASTIA VIDAL, sostre, 12", "C'AS CONCOS"),
        )

    def test_columna_direccion_por_bbox(self) -> None:
        row = [
            (9.5, 50.0, "HOLDER"),
            (167.75, 250.0, "STREET"),
            (503.0, 540.0, "123456789"),
        ]
        self.assertEqual(_page_column_x([row]), 168.0)
        cache: dict[int, float | None] = {}
        self.assertEqual(
            _resolve_ambiguous([ [row] ], 1, "123456789", cache),
            ("HOLDER", "STREET"),
        )
        self.assertIsNone(_resolve_ambiguous([ [row] ], 1, "999999999", cache))
        self.assertIsNone(_resolve_ambiguous(None, 1, "123456789", cache))

    def test_parse_date_line(self) -> None:
        self.assertEqual(parse_date_line("jueves, 1 de enero de 2026"), date(2026, 1, 1))
        self.assertEqual(parse_date_line("sábado, 28 de febrero de 2026"), date(2026, 2, 28))
        self.assertIsNone(parse_date_line("no es una fecha"))

    def test_parse_shift_header_variantes(self) -> None:
        self.assertEqual(
            parse_shift_header("SERVEI D'URGÈNCIA DIURN de 09:00 a 22:00"),
            ("diurna", time(9, 0), time(22, 0)),
        )
        self.assertEqual(
            parse_shift_header("SERVEI D'URGÈNCIA NOCTURN de 22:00 a 09:00"),
            ("nocturna", time(22, 0), time(9, 0)),
        )
        self.assertEqual(
            parse_shift_header("SERVEI D'URGÈNCIA NOCTURN PALMA de 21:00 a 09:00"),
            ("nocturna", time(21, 0), time(9, 0)),
        )
        self.assertEqual(
            parse_shift_header("SERVEI D'URGÈNCIA (09:00 - 09:00)"),
            ("24h", time(9, 0), time(9, 0)),
        )
        self.assertEqual(
            parse_shift_header("TORN DE REFORÇ (09:00 - 16:30)"),
            ("refuerzo", time(9, 0), time(16, 30)),
        )
        self.assertIsNone(parse_shift_header("ALGO SIN HORAS"))

    def test_fin_de_turno_al_dia_siguiente(self) -> None:
        day = date(2026, 3, 10)
        diurna = make_shift("IB:x", "Z", day, "diurna", time(9, 0), time(22, 0), "l")
        self.assertEqual(diurna.end, diurna.start.replace(hour=22))
        nocturna = make_shift("IB:x", "Z", day, "nocturna", time(22, 0), time(9, 0), "l")
        self.assertEqual(nocturna.end, nocturna.start.replace(day=11, hour=9))
        refuerzo = make_shift("IB:x", "Z", day, "refuerzo", time(9, 0), time(16, 30), "l")
        self.assertEqual(refuerzo.end.date(), day)

    def test_id_estable_entre_dias_y_zonas(self) -> None:
        a = pharmacy_id("REAL - REAL", "AV. DE LA CONSTITUCIÓ, 2", "971879321")
        b = pharmacy_id("Real - Real", "AV. DE LA CONSTITUCIÓ, 2", "971879321")
        c = pharmacy_id("REAL - REAL", "AV. DE LA CONSTITUCIÓ, 2 ", "971879321")
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        self.assertTrue(a.startswith("IB:"))
        self.assertEqual(len(a), 3 + 12)

    def test_normalize(self) -> None:
        self.assertEqual(normalize("  Mª  Magdalena  "), "MA MAGDALENA")
        self.assertEqual(normalize("CONSTITUCIÓ"), "CONSTITUCIO")


if __name__ == "__main__":
    unittest.main()

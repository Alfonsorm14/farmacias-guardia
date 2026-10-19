"""Tests de las propuestas de Murcia (no activadas): asignaciones en texto y rotaciones."""
from __future__ import annotations

import collections
import json
import os
import re
import unittest
from datetime import date, datetime

from ingesta.common import pdf_to_text
from ingesta.parsers.murcia_explicitos import FESTIVOS_REGION_2026, asignaciones
from ingesta.parsers.murcia_rotacion import (
    TZ,
    _parse_dates,
    evaluate_zone,
    project_zone,
    rule_texts,
    split_annexes,
    vacations,
)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF = os.path.join(BASE, "data", "raw", "murcia", "2026", "BORM_2025_6468.pdf")
OUT = os.path.join(BASE, "data", "out", "murcia_2026.json")


def _norm(texto: str) -> str:
    return re.sub(r"\s+", " ", texto)


class TestFechasVacaciones(unittest.TestCase):
    def test_formatos(self):
        casos = {
            "(del 14 al 16 y del 22 al 23 de agosto de 2026)": 5,
            "(los días 8 y 22 de agosto 2026)": 2,
            "del 17 de agosto al 2 septiembre de 2026.": 17,
            "13 de julio al 2 de agosto de 2026.": 21,
            "(los días 4 de abril, 2 de mayo, 7 y 31 de diciembre de 2026)": 4,
            "1, 8, 22 y 29 de agosto de 2026.": 4,
            "del 1 al 13 de septiembre, del 21 al 25 de diciembre, del 28 al 31 de diciembre de 2026)": 22,
        }
        for texto, n in casos.items():
            fechas, resto = _parse_dates(texto)
            self.assertEqual(len(fechas), n, texto)
            self.assertFalse(re.search(r"\d", resto), (texto, resto))


@unittest.skipUnless(os.path.exists(PDF), "falta el BORM")
class TestPropuestasMurcia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = pdf_to_text(PDF)
        cls.anexo_i, cls.anexo_iii = split_annexes(cls.text)
        cls.reglas = rule_texts(cls.anexo_iii)
        cls.vac, cls.avisos = vacations(cls.anexo_i)
        with open(OUT, encoding="utf-8") as fh:
            cls.data = json.load(fh)
        cls.by_zone = collections.defaultdict(list)
        for s in cls.data["shifts"]:
            cls.by_zone[s["zone"]].append(s)
        cls.zone_pharm = collections.defaultdict(set)
        for p in cls.data["pharmacies"]:
            for z in p["zones"]:
                cls.zone_pharm[z].add(p["id"])

    def _eval(self, zone):
        return evaluate_zone(zone, self.by_zone[zone], self.zone_pharm[zone], self.reglas, self.vac)

    def test_citas_literales_del_boletin(self):
        texto = _norm(self.text)
        ids = {p["id"] for p in self.data["pharmacies"]}
        for a in asignaciones():
            self.assertIn(_norm(a.cita), texto, a.zone)
            self.assertIn(a.pharmacy_id, ids)

    def test_dias_de_las_asignaciones(self):
        por_id = {a.pharmacy_id: a for a in asignaciones()}
        self.assertEqual(len(por_id["MU:383"].dias), 365)  # Albudeite, permanente
        self.assertEqual(len(por_id["MU:493"].dias), 26)  # Ifre-Cañada de Gallego
        # Isla Plana: 52 domingos + 10 festivos regionales (sin 1/1 ni 25/12) + 2 locales de Cartagena.
        isla = por_id["MU:433"].dias
        self.assertEqual(len(isla), 64)
        self.assertNotIn(date(2026, 1, 1), isla)
        self.assertIn(date(2026, 9, 25), isla)
        # Calabardina: domingos de julio y agosto + 15 de agosto, de 10 a 21 h.
        cala = por_id["MU:452"]
        self.assertEqual(len(cala.dias), 10)
        self.assertTrue(all(s["times_exact"] for s in cala.shifts()))
        self.assertEqual(len(FESTIVOS_REGION_2026), 12)

    def test_vacaciones_interpretadas(self):
        self.assertEqual(self.avisos, [])
        self.assertEqual(len(self.vac[5]["MU:524"]), 31)  # Mula: agosto entero

    def test_rotaciones_proyectables_y_bloqueadas(self):
        cieza = self._eval("AGRUPACION 44 (CIEZA)")
        self.assertTrue(cieza.proyectable)
        self.assertEqual((cieza.tipo, cieza.periodo), ("diaria", 12))
        ojos = self._eval("AGRUPACION 38 (OJOS)")
        self.assertEqual((ojos.tipo, ojos.periodo), ("semanal", 28))
        self.assertFalse(self._eval("AGRUPACION 18 (MAZARRON) - Mazarrón (casco)").proyectable)
        self.assertIn("2025", self._eval("AGRUPACION 37 (ARCHENA)").motivo)
        self.assertIn("librando", self._eval("AGRUPACION 26 (TOTANA)").motivo)

    def test_vacaciones_sin_turno_deducido(self):
        zone = "AGRUPACION 5 (MULA)"
        ev = self._eval(zone)
        proj = project_zone(ev, self.by_zone[zone], set())
        agosto = [s for s in proj if s["start"].startswith("2026-08") and s["pharmacy_id"] == "MU:524"]
        self.assertEqual(agosto, [])
        self.assertTrue(all(not s["times_exact"] and "DEDUCIDO" in s["raw_label"] for s in proj))
        dias = {datetime.fromisoformat(s["start"]).astimezone(TZ).date() for s in proj}
        self.assertEqual(min(dias), date(2026, 2, 1))
        self.assertEqual(max(dias), date(2026, 12, 31))

    def test_prueba_retrospectiva_fuente_alamo_falla_en_festivos(self):
        """El método aplicado a enero de Fuente Álamo (cuadrante anual publicado) falla en festivos:
        es la razón de que la proyección no se active sin decisión expresa."""
        zone = "AGRUPACION 20 (FUENTE ALAMO)"
        ss = self.by_zone[zone]
        dia = lambda s: datetime.fromisoformat(s["start"]).astimezone(TZ).date()  # noqa: E731
        jan = [s for s in ss if dia(s) < date(2026, 2, 1)]
        ev = evaluate_zone(zone, jan, {s["pharmacy_id"] for s in jan}, self.reglas, self.vac)
        self.assertTrue(ev.proyectable)
        pred = {dia(s): s["pharmacy_id"] for s in project_zone(ev, jan, set())}
        real = {dia(s): s["pharmacy_id"] for s in ss if dia(s) >= date(2026, 2, 1)}
        fallos = {d for d in real if pred.get(d) != real[d]}
        self.assertTrue(fallos)
        self.assertTrue({date(2026, 5, 1), date(2026, 10, 12), date(2026, 12, 25)} <= fallos)


if __name__ == "__main__":
    unittest.main()

"""Tests del parser de Zaragoza (servicio de farmacias de guardia del Ayuntamiento)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingesta.common import TZ
from ingesta.parsers.zaragoza import load_coordinates, parse_dir

SAMPLE = {
    "result": [
        {
            "id": 8860,
            "title": "Farmacia Prueba Prueba, Ana",
            "telefonos": "976226203",
            "calle": "Pº. de Sagasta, 8",
            "geometry": {"type": "Point", "coordinates": [-0.8858, 41.6461]},
            "guardia": {
                "fecha": "2026-10-19T00:00:00",
                "turno": "T-16",
                "horario": "Abiertas de 9:15 h. a 9:15 h. del día siguiente",
                "sector": "Sector Gran Vía",
            },
        },
        {"id": 1, "title": "Farmacia sin guardia", "calle": "X"},
    ]
}


class ZaragozaTests(unittest.TestCase):
    def test_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "farmacias_guardia_20261019.json"), "w", encoding="utf-8") as fh:
                json.dump(SAMPLE, fh)
            result = parse_dir(tmp)
            coords = load_coordinates(tmp)
        self.assertEqual(list(result.pharmacies), ["ZGZ:8860"])
        p = result.pharmacies["ZGZ:8860"]
        self.assertEqual(p.holder, "Prueba Prueba, Ana")
        self.assertEqual(p.phone, "976226203")
        s = result.shifts[0]
        self.assertEqual(s.kind, "24h")
        self.assertEqual(s.start, datetime(2026, 10, 19, 9, 15, tzinfo=TZ))
        self.assertEqual(s.end, datetime(2026, 10, 20, 9, 15, tzinfo=TZ))
        self.assertEqual(s.zone, "ZARAGOZA - Sector Gran Vía")
        self.assertEqual(coords["ZGZ:8860"], (41.6461, -0.8858))


if __name__ == "__main__":
    unittest.main()

"""Genera data/out/baleares_2026.json y muestra un resumen por consola."""
from __future__ import annotations

import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingesta.export import to_json
from ingesta.parsers.baleares import parse_dir

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "baleares", "2026")
OUT_PATH = os.path.join(BASE_DIR, "data", "out", "baleares_2026.json")
PALMA_DAY = date(2026, 10, 18)


def main() -> int:
    result = parse_dir(RAW_DIR)
    payload = to_json(result)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    print(f"Farmacias: {len(result.pharmacies)}")
    print(f"Turnos:    {len(result.shifts)}")
    print(f"Warnings:  {len(result.warnings)}")
    print(f"Salida:    {OUT_PATH}")
    print()
    print(f"Turnos de Palma del {PALMA_DAY.isoformat()}:")
    palma = [
        shift
        for shift in result.shifts
        if shift.zone == "PALMA" and shift.start.date() == PALMA_DAY
    ]
    for shift in sorted(palma, key=lambda s: (s.start, s.kind)):
        pharmacy = result.pharmacies[shift.pharmacy_id]
        print(
            f"  [{shift.kind:8}] {shift.start.strftime('%H:%M')}-"
            f"{shift.end.strftime('%H:%M')}  {pharmacy.holder}  "
            f"({pharmacy.phone})"
        )
    print(f"  total: {len(palma)} turnos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

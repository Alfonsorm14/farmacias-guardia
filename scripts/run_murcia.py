"""Genera data/out/murcia_2026.json y muestra un resumen por consola."""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingesta.export import to_json
from ingesta.parsers.murcia import parse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_PATH = os.path.join(
    BASE_DIR, "data", "raw", "murcia", "2026", "BORM_2025_6468.pdf"
)
OUT_PATH = os.path.join(BASE_DIR, "data", "out", "murcia_2026.json")
DAY = date(2026, 10, 18)


def _warnings_por_tipo(warnings: list[str]) -> Counter:
    codigos: Counter = Counter()
    for warning in warnings:
        match = re.match(r".*?p\d+: (\w+)", warning)
        codigos[match.group(1) if match else warning] += 1
    return codigos


def _turnos_del_dia(result, agrupacion: int) -> list:
    patron = re.compile(rf"AGRUPACION {agrupacion} \([^)]*\)( - .*)?$")
    return [
        shift
        for shift in result.shifts
        if shift.start.date() == DAY and patron.fullmatch(shift.zone)
    ]


def main() -> int:
    result = parse(PDF_PATH)
    payload = to_json(result)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    print(f"Farmacias: {len(result.pharmacies)}")
    print(f"Turnos:    {len(result.shifts)}")
    print(f"Warnings:  {len(result.warnings)}")
    print(f"Salida:    {OUT_PATH}")
    print()
    print("Warnings por tipo:")
    for code, total in _warnings_por_tipo(result.warnings).most_common():
        print(f"  {total:4}  {code}")
    print()
    print(f"Turnos del {DAY.isoformat()} (agrupaciones 1, 6 y 18):")
    for agrupacion in (1, 6, 18):
        turnos = _turnos_del_dia(result, agrupacion)
        print(f"  Agrupación {agrupacion}: {len(turnos)} turnos")
        for shift in sorted(turnos, key=lambda s: (s.zone, s.kind)):
            pharmacy = result.pharmacies[shift.pharmacy_id]
            print(
                f"    [{shift.kind:10}] {shift.start.strftime('%H:%M')}-"
                f"{shift.end.strftime('%H:%M')}  {shift.zone}  "
                f"{pharmacy.holder}  ({pharmacy.phone or 'sin tel.'})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

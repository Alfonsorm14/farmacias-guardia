"""Genera data/out/madrid_2026.json a partir de los PDF mensuales y del CSV anual de data/raw/madrid/.

Para añadir un mes nuevo: descargar el PDF vigente de
https://datos.madrid.es/dataset/214440-0-farmacias-guardia (recurso "Farmacias de
guardia", se sustituye cada mes) y guardarlo como data/raw/madrid/madrid_AAAA-MM.pdf; el CSV
"Farmacias de guardia AAAA" como data/raw/madrid/madrid_AAAA.csv (scripts/actualizar_todo.py lo hace).
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingesta.export import to_json  # noqa: E402
from ingesta.parsers.madrid import parse_dir  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(BASE_DIR, "data", "out", "madrid_2026.json")


def main() -> int:
    result = parse_dir(os.path.join(BASE_DIR, "data", "raw", "madrid"))
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(to_json(result), fh, ensure_ascii=False, indent=2)
    days = sorted({s.start.date() for s in result.shifts})
    print(f"Farmacias: {len(result.pharmacies)}")
    print(f"Turnos:    {len(result.shifts)} {dict(Counter(s.kind for s in result.shifts))}")
    if days:
        print(f"Días:      {days[0]} a {days[-1]}")
    print(f"Warnings:  {len(result.warnings)}")
    for w in result.warnings[:20]:
        print(f"  {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

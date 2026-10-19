"""Genera data/out/navarra_2026.json a partir de las descargas de data/raw/navarra/."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingesta.export import to_json  # noqa: E402
from ingesta.parsers.navarra import parse_dir  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "navarra")
OUT_PATH = os.path.join(BASE_DIR, "data", "out", "navarra_2026.json")


def main() -> int:
    result = parse_dir(RAW_DIR)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(to_json(result), fh, ensure_ascii=False, indent=2)
    days = sorted({s.start.date() for s in result.shifts})
    print(f"Farmacias: {len(result.pharmacies)}")
    print(f"Turnos:    {len(result.shifts)} {dict(Counter(s.kind for s in result.shifts))}")
    if days:
        print(f"Días:      {days[0]} a {days[-1]}")
    print(f"Warnings:  {len(result.warnings)}")
    print(f"Salida:    {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Genera Asturias solo para revisión local, tras activar ENABLE_ASTURIAS=true."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from ingesta.common import TZ
from ingesta.asturias_download import download
from ingesta.export import to_json
from ingesta.parsers.asturias import parse_dir


def enabled() -> bool:
    return os.environ.get("ENABLE_ASTURIAS", "false").lower() == "true"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sin-descargas", action="store_true")
    parser.add_argument("--start", type=date.fromisoformat, default=datetime.now(TZ).date())
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--raw", type=Path, default=BASE_DIR / "data/propuestas/asturias/raw")
    args = parser.parse_args()
    if not enabled():
        print("Asturias desactivada (ENABLE_ASTURIAS=false).")
        return 0
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        raise RuntimeError("Asturias solo permite revisión local hasta autorizar su reutilización")
    if args.end and args.end < args.start:
        parser.error("--end debe ser igual o posterior a --start")
    if not args.sin_descargas:
        download(args.raw, start=args.start, end=args.end)
    result = parse_dir(args.raw)
    if not result.pharmacies:
        raise ValueError("Sin fichas de Asturias para procesar")
    output = BASE_DIR / "data/propuestas/asturias/asturias.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(to_json(result), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    print(f"Asturias: {len(result.pharmacies)} farmacias, {len(result.shifts)} turnos, "
          f"{len(result.warnings)} avisos; revisión local: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

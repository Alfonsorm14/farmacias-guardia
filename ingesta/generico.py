"""CLI local del importador genérico; no realiza descargas ni publica datos."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import BadZipFile

from ingesta.export import to_json
from ingesta.parsers.generico import coverage_report, load_mapping, parse_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importa tablas locales mediante un mapeo YAML, sin completar datos ausentes.")
    parser.add_argument("--mapeo", required=True, type=Path, help="Mapeo YAML de la fuente")
    parser.add_argument("--entrada", required=True, type=Path, help="Fichero local XLSX, ODS, CSV o PDF")
    parser.add_argument("--salida", type=Path, help="JSON compatible con el importador existente")
    parser.add_argument("--solo-validar", action="store_true", help="No crea ni modifica la salida")
    args = parser.parse_args(argv)
    if not args.solo_validar and args.salida is None:
        parser.error("--salida es obligatorio salvo con --solo-validar")
    try:
        if args.salida is not None and args.salida.resolve() in {args.entrada.resolve(), args.mapeo.resolve()}:
            raise ValueError("La salida no puede sobrescribir la entrada ni el mapeo")
        mapping = load_mapping(args.mapeo)
        result = parse_file(args.entrada, mapping)
        coverage = coverage_report(result, mapping)
        print(json.dumps({"pharmacies": len(result.pharmacies), "shifts": len(result.shifts), "coverage": coverage}, ensure_ascii=False, indent=2))
        for warning in result.warnings:
            print(warning, file=sys.stderr)
        for gap in coverage["gaps"]:
            print(f"{args.entrada.name}: HUECO: {json.dumps(gap, ensure_ascii=False)}", file=sys.stderr)
        if result.warnings or coverage["gaps"]:
            print("Validación con incidencias: no se escribe la salida.", file=sys.stderr)
            return 1
        if not args.solo_validar:
            args.salida.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.salida.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    json.dump(to_json(result), stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                os.replace(temporary, args.salida)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return 0
    except (ValueError, OSError, LookupError, BadZipFile, ET.ParseError, csv.Error, KeyError, OverflowError) as exc:
        print(f"ERROR ({args.entrada}; mapeo {args.mapeo}): {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Descarga la ventana diaria de guardias de Navarra (y, si se pide, la capa IDENA).

El conjunto de datos abiertos solo contiene unas dos semanas; conviene ejecutarlo
a diario (tarea programada) para acumular el histórico en data/raw/navarra/.

Uso:
    python scripts/descargar_navarra.py            # guardias de hoy
    python scripts/descargar_navarra.py --idena    # además, capa oficial de farmacias
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.request
import zipfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingesta.parsers.navarra import DOWNLOAD_URL, IDENA_URL  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "navarra")
USER_AGENT = "farmacias-guardia/0.1 (alfonsorivero.es@gmail.com)"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--idena", action="store_true")
    args = parser.parse_args()
    os.makedirs(RAW_DIR, exist_ok=True)
    out = os.path.join(RAW_DIR, f"farmacias_guardia_{date.today():%Y%m%d}.json")
    data = _get(DOWNLOAD_URL)
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = None
    if not isinstance(parsed, dict) or "records" not in parsed:
        print("La respuesta no es el JSON esperado; no se guarda.", file=sys.stderr)
        return 1
    with open(out, "wb") as fh:
        fh.write(data)
    print(f"Guardias: {out} ({len(data)} bytes)")
    if args.idena:
        target = os.path.join(RAW_DIR, "idena")
        os.makedirs(target, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(_get(IDENA_URL))) as zf:
            for name in zf.namelist():
                if name.startswith("DOTACI_Sym_Farmacias.") and not name.endswith(".zip"):
                    zf.extract(name, target)
        print(f"IDENA: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

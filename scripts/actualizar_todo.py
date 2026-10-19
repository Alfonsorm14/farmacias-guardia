"""Actualiza todas las fuentes y la app de una vez (pensado para una tarea programada diaria).

Pasos:
1. Descarga lo que cambia a menudo: Navarra (ventana diaria) y Madrid (PDF del mes vigente).
2. Regenera data/out/*.json con los parsers.
3. Importa en data/guardias.db (las coordenadas se conservan si la dirección no cambia).
4. Geocodifica solo lo nuevo o pendiente (--recheck; la caché evita repetir consultas).
5. Exporta la instantánea de la app (app/assets/snapshot.json).

Baleares y Murcia son anuales: sus PDF se descargan a mano cuando sale el año nuevo.

Uso (Windows, desde la carpeta del proyecto):
    .venv\\Scripts\\python scripts\\actualizar_todo.py
    .venv\\Scripts\\python scripts\\actualizar_todo.py --sin-descargas   # solo reprocesar
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import urllib.request
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from ingesta.parsers.madrid import DOWNLOAD_URL as MADRID_URL  # noqa: E402

PY = sys.executable
USER_AGENT = "farmacias-guardia/0.1 (alfonsorivero.es@gmail.com)"


def _run(*args: str) -> None:
    print(f"\n$ {' '.join(args)}", flush=True)
    subprocess.run([PY, *args], cwd=BASE_DIR, check=True)


def _descargar_madrid() -> None:
    """Guarda el PDF vigente como madrid_AAAA-MM.pdf según el mes que declara su cabecera."""
    from ingesta.common import pdf_to_text

    req = urllib.request.Request(MADRID_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    tmp = os.path.join(BASE_DIR, "data", "raw", "madrid", "_descarga.pdf")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    with open(tmp, "wb") as fh:
        fh.write(data)
    text = pdf_to_text(tmp) or ""
    meses = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO",
             "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
    import re

    match = re.search(r"PERIODO\s+([A-Z]+)\s+(\d{4})", text)
    if not match or match.group(1) not in meses:
        os.remove(tmp)
        print("Madrid: no se reconoce el periodo del PDF; no se guarda.")
        return
    destino = os.path.join(
        BASE_DIR, "data", "raw", "madrid", f"madrid_{match.group(2)}-{meses.index(match.group(1)) + 1:02d}.pdf"
    )
    os.replace(tmp, destino)
    print(f"Madrid: {destino}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sin-descargas", action="store_true")
    args = parser.parse_args()
    if not args.sin_descargas:
        _run("scripts/descargar_navarra.py")
        try:
            _descargar_madrid()
        except OSError as exc:
            print(f"Madrid: descarga fallida ({exc}); se usa lo ya guardado.")
    _run("scripts/run_navarra.py")
    _run("scripts/run_madrid.py")
    _run("-m", "backend.importer", "data/out")
    _run("-m", "backend.geocode", "--recheck")
    _run("scripts/export_snapshot.py")
    print(f"\nActualización completada ({date.today():%d/%m/%Y}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

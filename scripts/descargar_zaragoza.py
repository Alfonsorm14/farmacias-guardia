"""Descarga las farmacias de guardia del día en Zaragoza (el servicio solo da el día en curso).

Ejecutar a diario para acumular el histórico en data/raw/zaragoza/.
"""
from __future__ import annotations

import os
import sys
import urllib.request
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingesta.parsers.zaragoza import DOWNLOAD_URL  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "zaragoza")


def main() -> int:
    os.makedirs(RAW_DIR, exist_ok=True)
    req = urllib.request.Request(DOWNLOAD_URL, headers={"User-Agent": "farmacias-guardia/0.1 (alfonsorivero.es@gmail.com)"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    out = os.path.join(RAW_DIR, f"farmacias_guardia_{date.today():%Y%m%d}.json")
    with open(out, "wb") as fh:
        fh.write(data)
    print(f"Zaragoza: {out} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

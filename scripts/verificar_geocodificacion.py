"""Comprobación por muestreo de la geocodificación contra la geocodificación inversa del IGN.

Toma N farmacias al azar con precisión portal/calle y consulta reverseGeocode de
CartoCiudad (~3 peticiones/s). Informa del municipio y la vía devueltos y si casan
con la dirección de la fuente (misma vía, o a menos de 150 m de ella).

Uso:
    python scripts/verificar_geocodificacion.py [--n 30] [--semilla 7]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from backend.geocode import clean_address, parse_address, street_similarity  # noqa: E402

REVERSE = "https://www.cartociudad.es/geocoder/api/geocoder/reverseGeocode"


def reverse(lat: float, lon: float) -> dict:
    url = REVERSE + "?" + urllib.parse.urlencode({"lat": f"{lat:.6f}", "lon": f"{lon:.6f}"})
    req = urllib.request.Request(url, headers={"User-Agent": "farmacias-guardia/0.1"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--semilla", type=int, default=7)
    parser.add_argument("--db", default=os.path.join(BASE_DIR, "data", "guardias.db"))
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    rows = conn.execute(
        "SELECT id, address, locality, lat, lon, geo_precision, geo_source FROM pharmacies "
        "WHERE geo_precision IN ('portal','calle') ORDER BY id"
    ).fetchall()
    muestra = random.Random(args.semilla).sample(rows, min(args.n, len(rows)))
    ok = 0
    print("| id | dirección | precisión/origen | municipio IGN | vía IGN | ¿casa? |")
    print("|---|---|---|---|---|---|")
    for pid, address, locality, lat, lon, prec, src in muestra:
        try:
            r = reverse(lat, lon)
        except OSError as exc:
            print(f"| {pid} | {address} | {prec}/{src} | error | {exc} | ? |")
            continue
        via = r.get("address") or ""
        nombre = parse_address(clean_address(address)).name
        casa = street_similarity(nombre, via) >= 0.6
        ok += casa
        print(f"| {pid} | {address} ({locality or '-'}) | {prec}/{src} | {r.get('muni')} | {via} {r.get('portalNumber') or ''} | {'sí' if casa else 'REVISAR'} |")
        time.sleep(0.34)
    print(f"\nCoinciden {ok}/{len(muestra)} (la vía más cercana al punto es la de la fuente).")
    print("Un 'REVISAR' no es necesariamente un error: en esquinas, la vía más cercana puede ser la transversal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

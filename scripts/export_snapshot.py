"""Exporta una instantánea compacta de data/guardias.db para la app (modo sin servidor).

Salida: app/assets/snapshot.json (JSON compacto). La app la usa cuando no hay un
backend configurado (--dart-define=API_BASE=...).

Formato:
{
  "version": 1, "generated_at": ISO-8601,
  "sources": [[source_id, publisher, url, license, retrieved_at], ...],
  "zones": [zona, ...],
  "pharmacies": [[id, titular, direccion, localidad, telefono, telefono_guardia,
                  lat, lon, precision, source_index], ...],
  "shifts": [[pharmacy_index, zone_index, inicio_min_utc, fin_min_utc, tipo, hora_exacta], ...]
}
`inicio_min_utc`/`fin_min_utc` son minutos desde 1970-01-01 UTC.

Uso:
    python scripts/export_snapshot.py [--db data/guardias.db] [--out app/assets/snapshot.json]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KINDS = {"diurna": "d", "nocturna": "n", "24h": "c", "localizada": "l", "refuerzo": "r"}


def _minutes(value: str) -> int:
    dt = datetime.datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return int(dt.timestamp() // 60)


def export(db_path: str, out_path: str) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    sources = conn.execute(
        "SELECT source_id, publisher, url, license, retrieved_at FROM sources ORDER BY source_id"
    ).fetchall()
    source_index = {row["source_id"]: i for i, row in enumerate(sources)}
    pharmacies = conn.execute("SELECT * FROM pharmacies ORDER BY id").fetchall()
    pharmacy_index = {row["id"]: i for i, row in enumerate(pharmacies)}
    shifts = conn.execute(
        "SELECT pharmacy_id, zone, start_utc, end_utc, kind, times_exact FROM shifts "
        "ORDER BY start_utc, pharmacy_id"
    ).fetchall()
    zones = sorted({row["zone"] for row in shifts})
    zone_index = {z: i for i, z in enumerate(zones)}

    def coord(value):
        return None if value is None else round(value, 6)

    data = {
        "version": 1,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "sources": [
            [r["source_id"], r["publisher"], r["url"], r["license"], r["retrieved_at"]] for r in sources
        ],
        "zones": zones,
        "pharmacies": [
            [
                r["id"], r["holder"], r["address"], r["locality"], r["phone"], r["duty_phone"],
                coord(r["lat"]), coord(r["lon"]), r["geo_precision"], source_index[r["source_id"]],
            ]
            for r in pharmacies
        ],
        "shifts": [
            [
                pharmacy_index[r["pharmacy_id"]], zone_index[r["zone"]],
                _minutes(r["start_utc"]), _minutes(r["end_utc"]),
                KINDS.get(r["kind"], r["kind"]), 1 if r["times_exact"] else 0,
            ]
            for r in shifts
        ],
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    conn.close()
    return {"farmacias": len(pharmacies), "turnos": len(shifts), "zonas": len(zones)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.path.join(BASE_DIR, "data", "guardias.db"))
    parser.add_argument("--out", default=os.path.join(BASE_DIR, "app", "assets", "snapshot.json"))
    args = parser.parse_args()
    stats = export(args.db, args.out)
    size = os.path.getsize(args.out) / 1024 / 1024
    print(f"{stats} -> {args.out} ({size:.1f} MB)")


if __name__ == "__main__":
    main()

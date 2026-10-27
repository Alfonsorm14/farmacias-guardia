"""Exporta una instantánea compacta de data/guardias.db para la app (modo sin servidor).

Salida: app/assets/snapshot.json (JSON compacto). La app la usa cuando no hay un
backend configurado (--dart-define=API_BASE=...).

Formato:
{
  "version": 1, "generated_at": ISO-8601,
  "sources": [[source_id, publisher, url, license, retrieved_at, solo_municipio], ...],
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
from contextlib import closing
import datetime
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# Fuentes que solo cubren un término municipal: la app no las usa fuera de él.
from backend.ambito import MUNICIPAL_SOURCES, SOURCE_AREAS, municipal_polygons  # noqa: E402
KINDS = {"diurna": "d", "nocturna": "n", "24h": "c", "localizada": "l", "refuerzo": "r"}


def _minutes(value: str) -> int:
    dt = datetime.datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return int(dt.timestamp() // 60)


def _validate_rows(sources: list, pharmacies: list, shifts: list) -> None:
    """Rechaza una extracción vacía o incoherente antes de preparar el destino."""
    for rows, key in ((sources, "source_id"), (pharmacies, "id"), (shifts, "id")):
        if not rows:
            raise ValueError("La instantánea requiere fuentes, farmacias y turnos no vacíos")
        ids = [r[key] for r in rows]
        if any(value is None or value == "" for value in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"Identificadores vacíos o duplicados: {key}")
    source_ids = {r["source_id"] for r in sources}
    pharmacy_sources = {r["id"]: r["source_id"] for r in pharmacies}
    if any(sid not in source_ids for sid in pharmacy_sources.values()):
        raise ValueError("Farmacia con fuente inexistente")
    for r in shifts:
        if (r["pharmacy_id"] not in pharmacy_sources or r["source_id"] not in source_ids
                or pharmacy_sources[r["pharmacy_id"]] != r["source_id"]):
            raise ValueError("Turno con farmacia o fuente incoherente")
        if not isinstance(r["zone"], str) or not r["zone"].strip():
            raise ValueError("Turno sin zona")
        if r["kind"] not in KINDS or r["times_exact"] not in (0, 1):
            raise ValueError("Tipo de turno o confirmación de horario inválidos")
        # El formato compacto usa minutos: una duración subminuto tampoco es publicable.
        if _minutes(r["end_utc"]) <= _minutes(r["start_utc"]):
            raise ValueError("Turno de duración no positiva en la instantánea")


def _validate_indices(data: dict) -> None:
    """Comprueba las referencias del formato compacto que recibirá la app."""
    def valid(value: int, rows: list) -> bool:
        return type(value) is int and 0 <= value < len(rows)

    if any(not valid(p[9], data["sources"]) for p in data["pharmacies"]):
        raise ValueError("Índice de fuente fuera de rango")
    for t in data["shifts"]:
        if not valid(t[0], data["pharmacies"]) or not valid(t[1], data["zones"]):
            raise ValueError("Índice de farmacia o zona fuera de rango")
        if t[3] <= t[2]:
            raise ValueError("Duración no positiva en el formato compacto")


def _write_atomic(data: dict, out_path: str) -> None:
    target = Path(out_path).absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=f".{target.name}.", suffix=".tmp", delete=False) as fh:
            temporary = Path(fh.name)
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export(db_path: str, out_path: str) -> dict[str, int]:
    # Solo lectura: una ruta errónea no debe crear una base vacía. La transacción mantiene
    # una vista coherente de las tres tablas aunque otro proceso actualice la base.
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        sources = conn.execute(
            "SELECT source_id, publisher, url, license, retrieved_at FROM sources ORDER BY source_id"
        ).fetchall()
        pharmacies = conn.execute("SELECT * FROM pharmacies ORDER BY id").fetchall()
        shifts = conn.execute(
            "SELECT id, pharmacy_id, source_id, zone, start_utc, end_utc, kind, times_exact FROM shifts "
            "ORDER BY start_utc, pharmacy_id"
        ).fetchall()
    _validate_rows(sources, pharmacies, shifts)
    source_index = {row["source_id"]: i for i, row in enumerate(sources)}
    pharmacy_index = {row["id"]: i for i, row in enumerate(pharmacies)}
    zones = sorted({row["zone"] for row in shifts})
    zone_index = {z: i for i, z in enumerate(zones)}

    def coord(value):
        return None if value is None else round(value, 6)

    data = {
        "version": 1,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "sources": [
            [r["source_id"], r["publisher"], r["url"], r["license"], r["retrieved_at"],
             r["source_id"] in MUNICIPAL_SOURCES,
             # Término municipal (polígonos [anillo exterior, huecos] de [lat, lon]) o null.
             [[[list(pt) for pt in ring] for ring in poly] for poly in municipal_polygons()[r["source_id"]]]
             if r["source_id"] in municipal_polygons() else None,
             # Ámbito para el usuario ("Illes Balears", "Madrid (ciudad)"...).
             SOURCE_AREAS.get(r["source_id"], r["publisher"])]
            for r in sources
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
                KINDS[r["kind"]], 1 if r["times_exact"] else 0,
            ]
            for r in shifts
        ],
    }
    _validate_indices(data)
    _write_atomic(data, out_path)
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

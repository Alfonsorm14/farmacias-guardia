"""Importador de ficheros data/out/*.json a base de datos relacional."""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from backend.db import create_db_engine, init_db

COORDS_PATH = Path(__file__).resolve().parent.parent / "data" / "geo" / "coordenadas.json"


def _load_coordinates() -> dict[str, dict[str, Any]]:
    """Coordenadas ya calculadas (data/geo/coordenadas.json), si existen."""
    try:
        return json.loads(COORDS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _apply_known_coordinates(pharmacy: Any, known: dict[str, dict[str, Any]]) -> None:
    """Reutiliza una geocodificación previa si la dirección, localidad y CP coinciden."""
    k = known.get(pharmacy.id)
    if not k or pharmacy.lat is not None:
        return
    if (k.get("direccion"), k.get("localidad"), k.get("cp")) != (
        pharmacy.address, pharmacy.locality, pharmacy.postal_code
    ):
        return
    pharmacy.lat, pharmacy.lon = k.get("lat"), k.get("lon")
    pharmacy.geo_precision, pharmacy.geo_source = k.get("precision"), k.get("fuente")
    pharmacy.geo_query = k.get("consulta")
from backend.models import Pharmacy, Shift, Source


def import_source_data(
    file_path: Path | str,
    session_factory: sessionmaker[Session] | None = None,
    reuse_coordinates: bool = True,
) -> dict[str, Any]:
    """Importa un fichero JSON de ingesta (data/out/*.json) de forma idempotente en una sola transacción."""
    path = Path(file_path)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    source_data = data["source"]
    source_id = source_data["source_id"]
    retrieved_at = datetime.datetime.fromisoformat(
        source_data["retrieved_at"]
    ).astimezone(datetime.timezone.utc)

    if session_factory is None:
        engine = create_db_engine()
        init_db(engine)
        session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with session_factory() as session:
        with session.begin():
            # 1. Upsert Source
            source = session.get(Source, source_id)
            if source is None:
                source = Source(
                    source_id=source_id,
                    publisher=source_data["publisher"],
                    url=source_data["url"],
                    license=source_data["license"],
                    retrieved_at=retrieved_at,
                )
                session.add(source)
            else:
                source.publisher = source_data["publisher"]
                source.url = source_data["url"]
                source.license = source_data["license"]
                source.retrieved_at = retrieved_at

            # 2. Upsert Pharmacies (mantener coordenadas si dirección, localidad y CP no cambian)
            pharmacies_count = 0
            known = _load_coordinates() if reuse_coordinates else {}
            for p_dict in data.get("pharmacies", []):
                pid = p_dict["id"]
                new_address = p_dict["address"]
                zones_json = json.dumps(
                    p_dict.get("zones", []), ensure_ascii=False
                )
                pharmacy = session.get(Pharmacy, pid)
                if pharmacy is None:
                    pharmacy = Pharmacy(
                        id=pid,
                        region=p_dict["region"],
                        holder=p_dict["holder"],
                        address=new_address,
                        locality=p_dict.get("locality"),
                        postal_code=p_dict.get("postal_code"),
                        phone=p_dict.get("phone"),
                        duty_phone=p_dict.get("duty_phone"),
                        source_id=source_id,
                        lat=None,
                        lon=None,
                        geo_source=None,
                        geo_precision=None,
                        geo_query=None,
                        zones=zones_json,
                    )
                    session.add(pharmacy)
                else:
                    location_changed = (
                        pharmacy.address != new_address
                        or pharmacy.locality != p_dict.get("locality")
                        or pharmacy.postal_code != p_dict.get("postal_code")
                    )
                    if location_changed:
                        # La dirección, localidad o CP cambió: hay que geocodificar de nuevo.
                        pharmacy.address = new_address
                        pharmacy.lat = None
                        pharmacy.lon = None
                        pharmacy.geo_source = None
                        pharmacy.geo_precision = None
                        pharmacy.geo_query = None

                    pharmacy.region = p_dict["region"]
                    pharmacy.holder = p_dict["holder"]
                    pharmacy.locality = p_dict.get("locality")
                    pharmacy.postal_code = p_dict.get("postal_code")
                    pharmacy.phone = p_dict.get("phone")
                    pharmacy.duty_phone = p_dict.get("duty_phone")
                    pharmacy.source_id = source_id
                    pharmacy.zones = zones_json
                _apply_known_coordinates(pharmacy, known)
                pharmacies_count += 1

            # 3. Borrar shifts del source_id e insertar nuevos
            session.execute(delete(Shift).where(Shift.source_id == source_id))

            seen_shifts: set[tuple[str, str, datetime.datetime, str]] = set()
            shifts_to_insert: list[Shift] = []
            for s_dict in data.get("shifts", []):
                st_utc = datetime.datetime.fromisoformat(s_dict["start"]).astimezone(
                    datetime.timezone.utc
                )
                end_utc = datetime.datetime.fromisoformat(s_dict["end"]).astimezone(
                    datetime.timezone.utc
                )
                key = (
                    s_dict["pharmacy_id"],
                    s_dict["zone"],
                    st_utc,
                    s_dict["kind"],
                )
                if key in seen_shifts:
                    continue
                seen_shifts.add(key)

                shifts_to_insert.append(
                    Shift(
                        pharmacy_id=s_dict["pharmacy_id"],
                        zone=s_dict["zone"],
                        start_utc=st_utc,
                        end_utc=end_utc,
                        kind=s_dict["kind"],
                        raw_label=s_dict["raw_label"],
                        times_exact=s_dict.get("times_exact", True),
                        source_id=source_id,
                    )
                )

            session.add_all(shifts_to_insert)

    summary = {
        "file": str(path),
        "source_id": source_id,
        "pharmacies": pharmacies_count,
        "shifts": len(shifts_to_insert),
    }
    print(
        f"Fuente {source_id} ({path.name}): {pharmacies_count} farmacias, {len(shifts_to_insert)} turnos importados."
    )
    return summary


def import_all(
    target_path: Path | str = "data/out",
    session_factory: sessionmaker[Session] | None = None,
    reuse_coordinates: bool = True,
) -> list[dict[str, Any]]:
    path = Path(target_path)
    if path.is_file():
        files = [path]
    elif path.is_dir():
        files = sorted(
            [
                p
                for p in path.glob("*.json")
                if not p.name.endswith("_v1.json")
            ]
        )
    else:
        raise FileNotFoundError(f"Ruta no encontrada: {target_path}")

    summaries = []
    for file in files:
        summary = import_source_data(
            file, session_factory=session_factory, reuse_coordinates=reuse_coordinates
        )
        summaries.append(summary)
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Importador de JSONs de ingesta a la base de datos."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="data/out",
        help="Directorio con ficheros JSON o ruta a un fichero JSON específico (por defecto data/out).",
    )
    args = parser.parse_args()
    import_all(args.path)


if __name__ == "__main__":
    main()

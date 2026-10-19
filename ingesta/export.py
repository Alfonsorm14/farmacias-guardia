"""Serialización del modelo de datos común a JSON.

`to_json(result)` devuelve un diccionario serializable con `json.dumps`:
fechas en ISO 8601 con offset (Europe/Madrid).
"""
from __future__ import annotations

from datetime import datetime

from ingesta.model import DutyShift, ParseResult, Pharmacy, SourceInfo


def _source_to_dict(source: SourceInfo) -> dict:
    return {
        "source_id": source.source_id,
        "publisher": source.publisher,
        "url": source.url,
        "license": source.license,
        "retrieved_at": source.retrieved_at.isoformat(),
    }


def _pharmacy_to_dict(pharmacy: Pharmacy, zones: list[str] | None = None) -> dict:
    data = {
        "id": pharmacy.id,
        "region": pharmacy.region,
        "holder": pharmacy.holder,
        "address": pharmacy.address,
        "locality": pharmacy.locality,
        "postal_code": pharmacy.postal_code,
        "phone": pharmacy.phone,
        "duty_phone": pharmacy.duty_phone,
    }
    if zones is not None:
        data["zones"] = zones
    return data


def _shift_to_dict(shift: DutyShift) -> dict:
    return {
        "pharmacy_id": shift.pharmacy_id,
        "zone": shift.zone,
        "start": shift.start.isoformat(),
        "end": shift.end.isoformat(),
        "kind": shift.kind,
        "raw_label": shift.raw_label,
        "times_exact": shift.times_exact,
    }


def to_json(result: ParseResult) -> dict:
    """Convierte un ParseResult en un diccionario serializable a JSON."""
    zones_by_pharmacy: dict[str, set[str]] = {}
    for shift in result.shifts:
        zones_by_pharmacy.setdefault(shift.pharmacy_id, set()).add(shift.zone)
    return {
        "source": _source_to_dict(result.source),
        "pharmacies": [
            _pharmacy_to_dict(
                result.pharmacies[pid], sorted(zones_by_pharmacy.get(pid, set()))
            )
            for pid in sorted(result.pharmacies)
        ],
        "shifts": [
            _shift_to_dict(shift)
            for shift in sorted(
                result.shifts,
                key=lambda s: (s.start, s.zone, s.pharmacy_id, s.kind),
            )
        ],
        "warnings": list(result.warnings),
    }

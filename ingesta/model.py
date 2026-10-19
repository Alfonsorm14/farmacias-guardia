"""Modelo de datos común para la ingesta de farmacias de guardia.

Contrato definido en docs/SPEC.md. No modificar sin aprobación.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Pharmacy:
    id: str
    region: str
    holder: str
    address: str
    locality: str | None
    postal_code: str | None
    phone: str | None
    duty_phone: str | None


@dataclass(frozen=True)
class DutyShift:
    pharmacy_id: str
    zone: str
    start: datetime
    end: datetime
    kind: str
    raw_label: str
    times_exact: bool = True


@dataclass(frozen=True)
class SourceInfo:
    source_id: str
    publisher: str
    url: str
    license: str
    retrieved_at: datetime


@dataclass
class ParseResult:
    source: SourceInfo
    pharmacies: dict[str, Pharmacy]
    shifts: list[DutyShift]
    warnings: list[str]

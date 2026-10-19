# Farmacias de guardia — Especificación de ingesta (v0.1)

Arquitecto y revisor: Claude. Implementación: OpenCode. Estándares: ver AGENTS.md.

## Objetivo
Convertir las fuentes OFICIALES de cada comunidad autónoma en un modelo de datos común,
que luego servirá un backend (FastAPI + PostgreSQL/PostGIS, fase posterior) a la app Flutter.

## Restricciones técnicas
- Python 3.10, solo librería estándar. Para PDF: `pdftotext -layout` (poppler-utils) vía subprocess.
  Cualquier dependencia nueva debe justificarse en la respuesta.
- Paquete `ingesta/`. Un módulo por fuente en `ingesta/parsers/<fuente>.py`.
- Tests con `unittest` en `tests/`, ejecutables con `python -m unittest discover -s tests -v`.
- Zona horaria: Europe/Madrid (Canarias: Atlantic/Canary). Usar `zoneinfo`.

## Modelo de datos (ingesta/model.py) — CONTRATO, no cambiar sin aprobación
```python
@dataclass(frozen=True)
class Pharmacy:
    id: str              # estable y reproducible: "<fuente>:<clave>"; ver cada parser
    region: str          # código INE de CCAA, p.ej. "04" Baleares, "14" Murcia
    holder: str          # titular/nombre tal como aparece en la fuente (normalizar espacios)
    address: str         # dirección tal como aparece, sin el teléfono
    locality: str | None # localidad si se puede extraer con seguridad; si no, None
    postal_code: str | None
    phone: str | None    # teléfono de la farmacia, solo dígitos (9 dígitos España)
    duty_phone: str | None  # teléfono específico de guardia si la fuente lo da aparte

@dataclass(frozen=True)
class DutyShift:
    pharmacy_id: str
    zone: str            # zona/agrupación de guardia tal como la nombra la fuente
    start: datetime      # aware, Europe/Madrid
    end: datetime        # aware; si end <= start en reloj, es del día siguiente
    kind: str            # "diurna" | "nocturna" | "24h" | "localizada" | "refuerzo"
    raw_label: str       # texto literal de la cabecera de turno en la fuente

@dataclass(frozen=True)
class SourceInfo:
    source_id: str       # p.ej. "IB-CAIB-2026"
    publisher: str
    url: str
    license: str         # p.ej. "CC BY-SA (aviso legal caib.es)"
    retrieved_at: datetime

@dataclass
class ParseResult:
    source: SourceInfo
    pharmacies: dict[str, Pharmacy]
    shifts: list[DutyShift]
    warnings: list[str]  # todo lo que no se pudo interpretar, con fichero y página
```
- `ingesta/export.py`: `to_json(result) -> dict` serializable (fechas ISO 8601 con offset).

## Reglas de calidad
- Nunca inventar datos: si un campo no se puede extraer con seguridad, None + warning.
- Nunca descartar en silencio una línea que parezca farmacia: warning con fichero, página y línea.
- Fuentes escaneadas (sin texto): warning "SIN_TEXTO" y se omite el fichero, salvo que exista al lado
  una transcripción verificada `<nombre>.txt` (mismo formato que `pdftotext -layout`); entonces se usa y
  se deja el aviso informativo "TRANSCRIPCION". Caso actual: Sant Antoni (Baleares), generada con
  `scripts/transcribir_sant_antoni.py` (cada línea se identifica por la huella de sus píxeles y las fechas
  se contrastan por OCR; cualquier línea desconocida detiene el proceso).

## Decisiones de producto (Alfonso, 18/10/2026)
- No se extrapolan reglas de rotación descritas en texto. Solo se publican turnos que la fuente
  asigna explícitamente a una farmacia y un día. Las zonas sin cuadrante explícito quedan sin cubrir
  (la app mostrará "sin datos oficiales para esta fecha") hasta disponer del cuadrante oficial.

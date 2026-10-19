# Tarea 03 — Geocodificación + backend API (MVP)

Ejecutor: Antigravity. Arquitecto/revisor: Claude. Lee antes AGENTS.md y docs/SPEC.md
(incluida la sección "Decisiones de producto").

## Límites
- NO modificar nada en `ingesta/`, `tests/test_baleares.py`, `tests/test_murcia.py` ni `data/raw/`.
  El backend solo CONSUME `data/out/*.json` (formato de `ingesta/export.py`).
- Todo el código nuevo en `backend/`. Tests en `backend/tests/` con pytest.
- Python 3.12, entorno virtual en `.venv/` (excluir de git). Dependencias permitidas, fijadas en
  `backend/requirements.txt`: fastapi, uvicorn, sqlalchemy (2.x), httpx, pytest. Cualquier otra, justificarla.
- Base de datos: SQLite en `data/guardias.db`, accedida SOLO mediante SQLAlchemy Core/ORM y sin SQL
  específico de SQLite, para poder migrar a PostgreSQL/PostGIS cambiando la URL de conexión
  (variable de entorno `DATABASE_URL`, por defecto `sqlite:///data/guardias.db`).
- Archivos temporales en `tmp/`.

## 1. Esquema
- `sources`: source_id (PK), publisher, url, license, retrieved_at.
- `pharmacies`: id (PK, el de la ingesta, p.ej. "IB:…", "MU:431"), region, holder, address, locality,
  postal_code, phone, duty_phone, source_id (FK), lat, lon (nullable), geo_source, geo_precision
  ("portal" | "calle" | "localidad" | null), geo_query (texto enviado al geocodificador).
- `shifts`: id (PK autoincremental), pharmacy_id (FK), zone, start_utc, end_utc (datetime en UTC),
  kind, raw_label, times_exact (bool), source_id (FK).
  Restricción única (pharmacy_id, zone, start_utc, kind). Índices en (start_utc, end_utc) y en pharmacy_id.
- `geocode_cache`: query normalizada (PK), lat, lon, precision, provider, raw_json, created_at.

## 2. Importador — `backend/importer.py`, CLI: `python -m backend.importer data/out`
- Lee todos los `data/out/*.json` excepto `*_v1.json`.
- Idempotente: upsert de sources y pharmacies (SIN borrar lat/lon ya calculadas si la dirección no cambió);
  shifts: borrar los del source_id y reinsertar, en una sola transacción por fuente.
- Convierte start/end (ISO con offset) a UTC. Imprime resumen por fuente.

## 3. Geocodificador — `backend/geocode.py`, CLI: `python -m backend.geocode [--limit N]`
- Proveedor principal: **CartoCiudad** (IGN/CNIG, servicio oficial de geocodificación de direcciones
  españolas, licencia CC BY 4.0). Verifica en su documentación oficial el endpoint vigente antes de usarlo
  y anota la URL de la documentación en un comentario.
- Respaldo: **Nominatim** (OSM) cumpliendo su política de uso: máximo 1 petición/segundo,
  User-Agent identificativo "farmacias-guardia/0.1 (alfonsorivero.es@gmail.com)", resultados cacheados.
- Consulta: dirección + localidad + código postal (si existe) + región ("Illes Balears" / "Región de Murcia"),
  limpiando ruido de la dirección: paréntesis descriptivos ("(davant del Corte Inglés)", "(Junto Carrefour)"),
  "Local N", "LOC. 7,8". Guardar en geo_query la consulta realmente enviada.
- Si no hay resultado a nivel de calle/portal: geocodificar la localidad y marcar geo_precision="localidad".
- Validación: descartar resultados fuera de la caja de su comunidad (Baleares lat 38.6–40.1, lon 1.1–4.4;
  Murcia lat 37.3–38.8, lon -2.4 a -0.6) -> warning y siguiente intento.
- Todo cacheado en geocode_cache: re-ejecutar no repite peticiones.
- Informe final: total, por precisión, fallidos (lista con id, dirección y motivo) en `tmp/geocode_report.txt`.

## 4. API — FastAPI en `backend/api.py`, arranque: `uvicorn backend.api:app --reload`
Zona horaria de presentación: Europe/Madrid (en respuestas, datetimes ISO con offset).

- `GET /health` -> {"status":"ok","pharmacies":N,"shifts":M}
- `GET /v1/guardias?lat=&lon=&at=&radius_km=25&limit=20`
  Farmacias de guardia en el instante `at` (ISO; por defecto ahora): start_utc <= at < end_utc.
  Ordenadas por distancia (haversine en Python; prefiltro por caja lat/lon en SQL).
  Turnos con times_exact=false (Murcia) se consideran activos todo el día natural de su fecha,
  y la respuesta lo indica con `"horario_confirmado": false`.
  Cada elemento: farmacia (id, titular, dirección, localidad, cp, teléfono, teléfono_guardia, lat, lon,
  geo_precision), turno (tipo, inicio, fin, zona, etiqueta_original, horario_confirmado), distancia_km,
  fuente (publisher, url, license).
  Además, a nivel raíz: `"cobertura"`: true si existe ALGÚN turno (de cualquier fecha) a menos de radius_km;
  false en caso contrario, con `"mensaje": "Sin datos oficiales para esta zona"`.
  Si cobertura es true pero no hay turnos en ese instante: `"mensaje": "Sin datos oficiales para esta fecha"`.
- `GET /v1/guardias/dia?lat=&lon=&fecha=YYYY-MM-DD&radius_km=25&limit=50`
  Turnos que se solapan con ese día natural (Europe/Madrid), misma forma de respuesta, ordenados por
  inicio y distancia. Es lo que usará la app para "mañana" y "pasado mañana".
- `GET /v1/farmacias/{id}` -> ficha + próximos 3 turnos.
- `GET /v1/fuentes` -> lista de fuentes con licencia (para la pantalla de atribución de la app).
- Farmacias sin lat/lon: no entran en /v1/guardias (no se puede calcular distancia); contarlas en
  `"farmacias_sin_coordenadas"` en la respuesta raíz.
- CORS abierto en desarrollo. Sin autenticación en el MVP.

## 5. Tests (pytest, `backend/tests/`), sin red
- Fixture: BD temporal importada desde los JSON reales de data/out; coordenadas inyectadas en el test
  para las farmacias usadas (no depender del geocodificador).
- Palma (39.5696, 2.6502), at=2026-10-18T23:00+02:00 -> exactamente las 3 nocturnas de Palma
  (ALCOVER CASASNOVAS, R; GOMEZ GARCIA; REAL VICENS), horario_confirmado true.
- Palma, at=2026-10-18T12:00+02:00 -> incluye las 19 diurnas de Palma.
- Alcantarilla (37.969, -1.217), at=2026-01-01T03:00+01:00 -> MU:431, horario_confirmado false.
- Burgos (42.344, -3.696) -> cobertura false, lista vacía, mensaje "Sin datos oficiales para esta zona".
- Mazarrón (37.598, -1.314), fecha 2026-10-18 -> cobertura true, lista vacía,
  mensaje "Sin datos oficiales para esta fecha" (agrupación sin cuadrante: decisión de producto).
- Cambio de hora: un turno nocturno 2026-10-24 22:00 -> 2026-10-25 09:00 Europe/Madrid dura 12 h reales.
- Importador idempotente: importar dos veces no duplica turnos ni pierde coordenadas.
- Todos los tests existentes de la ingesta siguen pasando (`python -m unittest discover -s tests`).

## Entrega
Resumen según AGENTS.md + `docs/BACKEND.md` breve (cómo importar, geocodificar, arrancar, ejemplos curl).

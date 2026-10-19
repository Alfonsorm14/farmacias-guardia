# Backend y API REST — Farmacias de Guardia (v0.1 MVP)

Backend desarrollado con **FastAPI** y **SQLAlchemy 2.0** para servir los datos de farmacias de guardia oficiales (Baleares y Murcia) a la aplicación Flutter y otros clientes.

---

## 1. Requisitos e Instalación

Requiere Python 3.12. Las dependencias están fijadas en `backend/requirements.txt`:

```powershell
# Crear y activar el entorno virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Instalar dependencias
pip install -r backend/requirements.txt
```

> **Nota sobre dependencias:** Se incluye `tzdata` para dar soporte a la base de datos horaria IANA (`Europe/Madrid`) en sistemas Windows a través de la librería estándar `zoneinfo`.

---

## 2. Importación de Datos

El importador lee los ficheros oficiales generados por la ingesta (`data/out/*.json`, excluyendo `*_v1.json`) y realiza un upsert idempotente en la base de datos relacional (por defecto `data/guardias.db`). Si una farmacia ya contaba con coordenadas calculadas y su dirección no ha cambiado, las coordenadas se conservan intactas.

```powershell
python -m backend.importer data/out
```

---

## 3. Geocodificación (Tareas 03b y 03c)

El geocodificador (`backend/geocode.py`) resuelve las coordenadas de las farmacias cumpliendo estrictamente con la eliminación de coordenadas falsas o centros fijos:
1. **Sin coordenadas fijas:** Prohibidas las constantes de coordenadas de respaldo (salvo las cajas geográficas oficiales `BBOXES`). Ningún valor prefijado de prueba.
2. **Normalización avanzada:** Limpieza de cruces (`ESQUINA...`), supresión de `S/N`, `Nº`, paréntesis descriptivos, unidades comerciales (`Local N`, `LOC. 7,8`), expansión de abreviaturas viales (`CALLE`, `AVENIDA`, `CARRETERA`, `PLAZA`, etc.) y separación de caracteres pegados.
3. **Resolución de municipio y núcleo (pedanía):**
   - **Murcia:** Desglose de `X (MUNICIPIO)` y mapeo de las 157 localidades/pedanías regionales (ej. *Los Belones* -> municipio Cartagena; *La Raya*, *El Palmar* -> municipio Murcia).
   - **Baleares:** Mapeo exhaustivo de pedanías e islas (ej. *Cala Rajada* -> Capdepera; *Port d'Andratx* -> Andratx; *Sant Ferran* -> Formentera; *Peguera*, *Santa Ponça*, *Cas Català* -> Calvià; *Ciutadella de Menorca*).
4. **Estrategia en cascada:**
   - **CartoCiudad (IGN/CNIG):** Endpoints `candidates` y `find` con filtros estructurados (`municipio_filter`, `comunidad_autonoma_filter`), priorizando candidatos pertenecientes al núcleo.
   - **Nominatim (OpenStreetMap):** En modo estructurado (`street`, `city`, `countrycodes=es`, 1 req/s).
   - **Precisión Localidad:** Si la calle/portal no se localiza, se sitúa en el **centroide dinámico del núcleo de población (pedanía)**, nunca en el del municipio. Si no se puede situar ni la dirección ni el núcleo, `lat/lon = NULL` (nunca puntos falsos).
5. **Control de calidad y puntos compartidos:**
   - Distancia al centroide de referencia validada (< 5 km para pedanías, < 15 km para cascos urbanos).
   - Ningún par `(lat, lon)` puede ser compartido por más de 2 farmacias salvo que compartan la misma dirección normalizada (los excesos se degradan a `lat/lon = NULL`).
6. **Reprocesamiento:** Soporta `--recheck` para reprocesar farmacias a localidad, pendientes o en centroides.

```powershell
# Geocodificar todas las farmacias pendientes
python -m backend.geocode

# Reprocesar farmacias afectadas y generar informe
python -m backend.geocode --recheck --report tmp/geocode_report.txt
```

El informe final de resultados se genera automáticamente en `tmp/geocode_report.txt`.

---

## 4. Arranque de la API

Para iniciar el servidor de desarrollo en `http://127.0.0.1:8000`:

```powershell
uvicorn backend.api:app --reload
```

---

## 5. Endpoints y Estructura de Respuesta

### Formato Unificado y Claves Limpias
- `/v1/guardias` y `/v1/guardias/dia` devuelven una única lista `guardias` (se eliminaron listas redundantes como `turnos` o `resultados`).
- Todas las claves del objeto `farmacia` van estrictamente **sin tildes**: `direccion`, `telefono`, `telefono_guardia`.
- `ubicacion_aproximada`: `true` cuando `geo_precision == "localidad"` (centroide de núcleo o municipio), `false` en caso contrario.
- `farmacias_sin_coordenadas`: cuenta exclusivamente farmacias con turno activo en el momento consultado cuyas `zones` coincidan con las de las farmacias cercanas encontradas (ámbito local, no nacional).

### Health Check
Comprueba el estado y el conteo de farmacias y turnos cargados.
```bash
curl -X GET "http://127.0.0.1:8000/health"
```
**Respuesta:**
```json
{
  "status": "ok",
  "pharmacies": 834,
  "shifts": 56136
}
```

### Fuentes Oficiales
Lista las fuentes de datos oficiales con atribución y licencias.
```bash
curl -X GET "http://127.0.0.1:8000/v1/fuentes"
```

### Farmacias de Guardia en un Instante (`/v1/guardias`)
Devuelve las farmacias de guardia activas en el instante dado (por defecto `now`), ordenadas por distancia ortodrómica.
```bash
curl -X GET "http://127.0.0.1:8000/v1/guardias?lat=39.5696&lon=2.6502&at=2026-10-18T23:00:00%2B02:00&radius_km=25"
```
**Campos clave:**
- `cobertura`: `true` si hay cobertura oficial en la zona; `false` si no hay datos oficiales en el radio de búsqueda (`"mensaje": "Sin datos oficiales para esta zona"`).
- `mensaje`: `"Sin datos oficiales para esta fecha"` cuando hay farmacias en la zona pero ninguna con turno activo en el momento consultado.
- `farmacias_sin_coordenadas`: Conteo localizado de farmacias con turno activo en la zona que carecen de coordenadas.
- `guardias`: Lista única donde cada elemento contiene `farmacia`, `turno` (`horario_confirmado`), `distancia_km` y `fuente`.

### Turnos del Día (`/v1/guardias/dia`)
Devuelve todos los turnos que se solapan con la fecha natural indicada (en hora `Europe/Madrid`), ordenados por hora de inicio y distancia dentro de la lista única `guardias`.
```bash
curl -X GET "http://127.0.0.1:8000/v1/guardias/dia?lat=37.969&lon=-1.217&fecha=2026-01-01&radius_km=25"
```

### Ficha Detallada de Farmacia (`/v1/farmacias/{id}`)
Obtiene la información de la farmacia y sus próximos 3 turnos programados.
```bash
curl -X GET "http://127.0.0.1:8000/v1/farmacias/IB:0efd04c9a719"
```

---

## 6. Ejecución de Tests

```powershell
# Tests del backend (pytest, sin red, con coordenadas inyectadas y fixtures)
.\.venv\Scripts\python -m pytest backend/tests -v

# Tests de regresión de la ingesta (unittest estándar)
python -m unittest discover -s tests -v
```

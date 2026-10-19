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

El importador lee los ficheros oficiales generados por la ingesta (`data/out/*.json`, excluyendo `*_v1.json`) y realiza un upsert idempotente en la base de datos relacional (por defecto `data/guardias.db`). Si una farmacia ya contaba con coordenadas y no han cambiado ni su dirección, ni su localidad, ni su código postal, las coordenadas se conservan.

```powershell
python -m backend.importer data/out
```

---

## 2 bis. Actualización diaria (todas las fuentes)

```powershell
.venv\Scripts\python scripts\actualizar_todo.py
```
Descarga Navarra (ventana diaria de datos abiertos) y el PDF vigente de Madrid ciudad, regenera
`data/out/*.json`, importa, geocodifica solo lo nuevo y exporta la instantánea de la app. Conviene
programarlo a diario (Programador de tareas de Windows). Baleares y Murcia son anuales.

---

## 3. Geocodificación (v4, 19/10/2026)

`backend/geocode.py` sitúa cada farmacia con CartoCiudad (IGN) y Nominatim (OSM). Sustituye a la versión de las Tareas 03b/03c, cuya revisión detectó pedanías en el centroide de su municipio, una comparación de municipios por subcadena ("Murcia" aceptaba resultados de "Alhama de Murcia") y resultados de Nominatim de cualquier tipo contados como "calle".

1. **Sin coordenadas fijas.** Las únicas constantes geográficas son las cajas `BBOXES` por comunidad.
2. **Validación de cada punto.** Todo punto aceptado se comprueba con `reverseGeocode` de CartoCiudad: su municipio debe ser el esperado (igualdad exacta normalizada, sin artículos y con alias bilingües: Maó/Mahón, Eivissa/Ibiza, Santa Eulària/Santa Eulalia…). Excepción: núcleos repartidos entre dos municipios (Cala Millor: Son Servera y Sant Llorenç), se acepta el vecino si el punto está a ≤ 1 km del núcleo.
3. **Vía y código postal.** Un resultado solo cuenta si el nombre de la vía coincide con el de la fuente (similitud de palabras significativas ≥ 0,6) y, si la farmacia trae CP (Murcia), si coincide el CP. En Murcia la búsqueda se filtra por CP (`cod_postal_filter`), lo que evita confundir, p. ej., la Calle Mayor de Puente Tocinos con la de otra pedanía.
4. **Precisión.** `portal` = portal con el mismo número; `calle` = misma vía sin ese número exacto; `localidad` = centroide de la entidad de población (núcleo/pedanía) de CartoCiudad (`geo_source = nucleus_centroid`), o del núcleo principal del municipio solo si la fuente da localidad = municipio (`casco_centroid`). Si no hay ni dirección ni núcleo: `lat/lon = NULL`.
5. **Núcleo esperado.** Murcia: localidad de la fuente ("X (MUNICIPIO)", "NUCLEO-MUNICIPIO", mapas de pedanías) y, si la localidad es el municipio, pistas de la dirección ("MAYOR, 104 - PUENTE TOCINOS"). Baleares: localidad de la fuente; si falta, núcleo citado en la dirección ("… 11 CALA MILLOR", "(ES CANAR)") y, si no, los municipios de sus zonas de guardia (sin centroide de respaldo).
6. **Control final.** Ningún punto compartido por más de 2 farmacias con direcciones distintas.
7. **Caché.** Cada respuesta de los servicios se guarda en `geocode_cache` (claves `v4:`), así que repetir la geocodificación no vuelve a consultar lo ya consultado (`--offline` usa solo la caché).

```powershell
python -m backend.geocode                 # todas las farmacias
python -m backend.geocode --recheck       # solo localidad o sin coordenadas
python -m backend.geocode --ids MU:302,IB:5b84a70432fe
```

Informe: `tmp/geocode_report.txt` (totales, puntos compartidos, lista de farmacias a nivel localidad y sin coordenadas con el motivo, y muestra de 20 enlaces OSM para revisión manual).

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
- `ubicacion_aproximada`: `true` cuando `geo_precision == "localidad"` (centroide del núcleo de población), `false` en caso contrario.
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

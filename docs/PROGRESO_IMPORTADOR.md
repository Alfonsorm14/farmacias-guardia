# Progreso del importador genérico de transparencia

Estado: **implementado y comprobado** en el mismo PR #2, rama `codex/importador-generico-transparencia`, creada desde `main`. El bloqueo de arranque de la primera entrega se ha resuelto.

## Resultado

- `ingesta/parsers/generico.py`: mapeo YAML versión 1, filas y matrices, franjas explícitas, normalización, constantes documentadas, exclusiones, errores por fila, identidad estable, duplicados, conflictos y cobertura por fecha/zona con huecos diarios u horarios.
- `ingesta/parsers/_tabular.py`: lectores XLSX/ODS/CSV con biblioteca estándar y PDF básico por columnas reutilizando `pdf_to_text` de `ingesta.common`. No se evalúan fórmulas ni se realiza OCR.
- `ingesta/generico.py`: CLI con validación sin escritura, resumen, códigos de salida y escritura atómica únicamente sin incidencias.
- `ingesta/mapeos/ejemplo.yaml`: plantilla comentada. `docs/IMPORTADOR_GENERICO.md`: guía en español y descripción de integración futura en el workflow, sin modificarlo.
- Cuatro fuentes inventadas con sus mapeos en `tests/fixtures/generico/`: XLSX por guardia, CSV con franjas, calendario ODS y PDF tabular. Incluyen errores deliberados y un generador reproducible, sin red. No contienen datos reales de farmacias.
- `tests/test_generico.py`: 27 tests nuevos del importador, lectores y CLI, además de casos parametrizados. `backend/tests/test_generico.py`: cuatro casos de integración del JSON en el importador existente, idempotentes, con SQLite aislado y sin coordenadas.

## Dependencia justificada

Se incorpora únicamente PyYAML 6.0.3 en `ingesta/requirements.txt` para admitir YAML mediante un cargador seguro y evitar un lector parcial propio. `backend/requirements.txt` incluye esos requisitos porque el workflow existente ejecuta la suite de ingesta tras instalar las dependencias del backend. No se modifica el workflow. Los lectores de hojas no incorporan dependencias nuevas.

## Comprobaciones ejecutadas

Desde la raíz, en el entorno virtual local:

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pytest backend/tests -q
```

- Ingesta: **98 tests, OK; 1 omitido existente** porque requiere una copia local de la versión 1 que no está en Git. Los otros 97 pasan, incluidos todos los nuevos.
- Backend: **101 tests pasan**. Se conserva un aviso de deprecación de la infraestructura existente de Starlette/httpx.

Desde `app/`, con Flutter **3.47.8** descargado del archivo oficial y verificado con el SHA-256 fijado en el workflow existente:

```sh
flutter pub get --enforce-lockfile
flutter analyze --no-pub
flutter test --no-pub
```

- Dependencias resueltas sin cambiar el lockfile.
- Análisis: **sin incidencias**.
- Flutter: **61 tests pasan**.

El entorno tiene el directorio personal de solo lectura. Para ejecutar Flutter se han situado sus cachés y estado bajo `/workspace/tools` mediante `PUB_CACHE`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME` y `ANALYZER_STATE_LOCATION_OVERRIDE`, con `FLUTTER_SUPPRESS_ANALYTICS=true` y `DASH__SUPPRESS_ANALYTICS=true`. No se ha modificado la app para adaptar el entorno.

También se ha validado la plantilla YAML y ejecutado `git diff --check`.

## Alcance y límites

No se han descargado fuentes reales ni modificado URLs existentes, workflows, Pages, firma, applicationId, snapshot, coordenadas, modelo de datos, importador del backend ni parsers actuales. Se han ejecutado los tests existentes sobre los documentos ya presentes, sin descargar ni actualizar datos.

El PDF básico requiere una fila visual por registro y columnas verificadas sobre la extracción local. Las fuentes escaneadas, celdas combinadas sin datos, horarios ambiguos y marcas desconocidas no se completan. La cobertura solo puede detectar zonas y periodos totalmente ausentes si se declaran en el mapeo. La guía documenta estas limitaciones y el uso de identificadores exclusivos por provincia/hoja para no sustituir otra fuente.

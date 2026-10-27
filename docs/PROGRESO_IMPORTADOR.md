# Progreso del importador genérico de transparencia

Estado: **incompleto; no integrar todavía**. Rama nueva creada desde `main`: `codex/importador-generico-transparencia`.

## Trabajo realizado

- Leído `AGENTS.md` y contrastado el contrato de `docs/SPEC.md`, `ingesta/model.py` e `ingesta/export.py`.
- Revisadas las utilidades de PDF de `ingesta/common.py`, el parser de Madrid y su suite, la estructura del backend y los comandos de comprobación del workflow existente.
- No se han descargado fuentes reales ni añadido fixtures. No se han modificado URLs existentes, workflows, Pages, firma, applicationId, snapshot, coordenadas ni parsers actuales.
- El único cambio de esta entrega es este documento. El importador, el CLI y sus tests **todavía no están implementados**.

## Bloqueo del entorno

El entorno de ejecución asignado permanece en `pending`, con conectividad `offline` y sin capacidades de ejecución. Se ha usado la herramienta de espera y consultado el estado y los diagnósticos; no hay evidencia de diagnóstico retenida. El intento de ejecutar comandos devuelve que no existe un entorno utilizable. El acceso al repositorio mediante el conector de GitHub sí funciona.

No se han ejecutado tests de Python ni Flutter. **No se afirma que estén en verde**. No se ha invocado el workflow de actualización porque descarga fuentes y modifica datos fuera del alcance autorizado.

## Diseño comprobado y trabajo pendiente

### Contrato e integración

`ingesta/parsers/generico.py` debe devolver el mismo `ParseResult` que los parsers existentes: `SourceInfo`, diccionario de `Pharmacy`, lista de `DutyShift` y avisos. El JSON debe generarse con `ingesta.export.to_json`, sin modificar el modelo ni el importador del backend. Las zonas horarias deben ser explícitas mediante `zoneinfo`, incluida `Atlantic/Canary` cuando corresponda.

`python -m ingesta.generico --mapeo X.yaml --entrada fichero --salida data/out/X.json --solo-validar` debe validar sin escribir la salida cuando se use `--solo-validar`. Debe ofrecer errores de configuración legibles y códigos de salida documentados; una importación con filas inválidas no debe pasar por válida silenciosamente.

### Mapeo por fuente

Añadir `ingesta/mapeos/` con un ejemplo comentado, exclusivamente ficticio, que describa:

- Metadatos de fuente, región, espacio de identificadores y zona horaria.
- Tipo CSV, XLSX, ODS o PDF; codificación y delimitador; hoja o página; fila de cabecera e inicio de datos.
- Columnas de nombre, dirección, municipio, código postal, teléfono, código/NIF, zona, fecha, inicio, fin, franja y tipo de guardia.
- Formatos de fecha y hora, franjas declaradas, normalizaciones permitidas, valores por defecto explícitos y reglas para ignorar filas.
- Matrices con días por columnas: columnas de identificación de farmacia, fechas de las columnas y significado explícito de cada marca. Una celda vacía no crea un turno.

Evaluar lectores de hojas con `zipfile` y `xml.etree.ElementTree` de la biblioteca estándar: XLSX con relaciones de hojas, shared strings, inline strings y fechas nativas; ODS con celdas repetidas, tipos y hojas. No cargar dependencias de hojas por comodidad. YAML necesita una decisión explícita: si se incorpora PyYAML, declarar la dependencia en un fichero de requisitos de ingesta, justificarla en el PR y usar carga segura. No implementar un lector YAML parcial que acepte mal configuraciones válidas.

Para PDF tabulares reutilizar `pdf_bbox_pages` o `pdf_to_text` de `ingesta.common`, con un modo básico por columnas y selección de página. Advertir sobre PDF sin texto, filas truncadas y tablas fuera de las posibilidades del modo básico; no inventar transcripciones ni aplicar OCR implícito.

### Validación y cobertura

- Cada rechazo debe identificar fichero, hoja/página cuando proceda, fila y motivo. No descartar filas desconocidas en silencio.
- Comprobar columnas, campos obligatorios, fechas, horarios, tipo de guardia y conflictos de identidad; conservar como ausentes los campos opcionales no disponibles y advertir si su contenido es inválido.
- Los identificadores deben ser reproducibles; si no hay código/NIF, documentar una clave técnica derivada de campos presentes sin fingir un identificador oficial.
- Tratar correctamente turnos que cruzan medianoche y límites de cambio horario; no inferir una franja que el mapeo no declare.
- Detectar duplicados y conflictos sin sobrescribir registros diferentes silenciosamente.
- Resumir cobertura por fecha y zona y detectar huecos dentro de un periodo y zonas explícitamente declarados o, si se usa el intervalo observado, indicar esa limitación. Nunca completar huecos.

### Fixtures y tests pendientes

Crear cuatro fuentes inventadas y sus mapeos: XLSX con una fila por guardia, CSV con franjas, matriz calendario (preferentemente ODS para cubrir también ese lector) y PDF tabular sencillo. Nombres, direcciones y teléfonos deben ser inventados. Probar también configuración inválida, columnas ausentes, fechas y horas erróneas, campos opcionales, filas ignoradas, duplicados, conflictos, huecos, medianoche, selección de hoja/página, celdas vacías y repetidas, y CLI con `--solo-validar` sin escritura.

Comprobar de extremo a extremo que la salida del parser se serializa con el exportador existente y la acepta el importador del backend sin cambios.

### Documentación pendiente

Crear `docs/IMPORTADOR_GENERICO.md` en español con el procedimiento paso a paso para añadir una comunidad o provincia cuando llegue su respuesta, adaptar su mapeo, validar, revisar avisos/cobertura y generar JSON. Describir cómo se integraría en el workflow, **sin modificarlo ni ejecutarlo**. Identificadores del código y del esquema en inglés.

## Comprobaciones que faltan antes de marcar el PR como listo

Desde la raíz del repositorio:

```sh
python -m unittest discover -s tests -v
python -m pytest backend/tests -q
```

Desde `app/`, con el Flutter compatible con el repositorio:

```sh
flutter pub get --enforce-lockfile
flutter analyze
flutter test
```

Instalar únicamente las dependencias necesarias y justificadas. No ejecutar `scripts/actualizar_todo.py` ni scripts de descarga, geocodificación o exportación de snapshot. Revisar el diff final para confirmar que todos los cambios están dentro del alcance y actualizar este documento con resultados reales antes de dar el trabajo por terminado.

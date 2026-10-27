# Importador genérico de respuestas de transparencia

Permite incorporar una tabla nueva de una comunidad autónoma, Ceuta, Melilla o una provincia mediante un fichero YAML. No descarga documentos: trabaja con una respuesta local recibida por transparencia. La salida usa `ParseResult` y `ingesta.export.to_json`, el contrato que ya acepta `backend.importer`.

## 1. Preparar el entorno

Desde la raíz del repositorio, con Python 3.10 o posterior:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r ingesta/requirements.txt
```

Para PDF tabulares también se necesita `pdftotext` de `poppler-utils`, igual que en los parsers existentes. Para comprobar el backend, instalar además `backend/requirements.txt`, que incluye los requisitos de ingesta.

La única dependencia nueva es **PyYAML 6.0.3**: la biblioteca estándar no lee YAML. Se utiliza su cargador seguro, sin ejecutar etiquetas de objetos Python, rechazando claves explícitas duplicadas y opciones desconocidas. Se admiten anclas y mezclas YAML. Los lectores XLSX y ODS usan `zipfile` y `xml.etree.ElementTree`; CSV usa `csv`. No se necesitan pandas, openpyxl ni odfpy.

## 2. Inspeccionar la respuesta local

Conservar el documento recibido y su procedencia. Comprobar manualmente qué hoja/página contiene la tabla, dónde está la cabecera, qué significa cada columna y qué periodo y zonas cubre. No deducir horarios, municipios o farmacias a partir de una rotación o de otra fuente.

- **XLSX/ODS:** se selecciona una sola hoja por nombre exacto o índice base uno. Se leen celdas vacías y dispersas, texto, fechas y horas nativas. XLSX admite shared strings, inline strings y los calendarios 1900/1904. ODS admite filas y celdas repetidas. No se evalúan fórmulas: solo sirven sus resultados almacenados. Un error de celda o fórmula sin resultado en un campo utilizado genera una incidencia. Las celdas combinadas no se rellenan.
- **CSV:** declarar delimitador y codificación. Se respetan comillas y saltos de línea dentro de un campo. Los números de fila son líneas físicas del documento —la última línea de un registro si ocupa varias—.
- **PDF:** debe contener texto y una fila visual por registro. Revisar localmente `pdftotext -layout respuesta.pdf -`. `column_starts` son posiciones de carácter en **esa salida**, empezando en cero; cada columna termina donde empieza la siguiente y la última llega al final. No son coordenadas geográficas. `pages` selecciona páginas base uno; si se omite, se leen todas. La cabecera se interpreta por separado en cada página. Se reutiliza `ingesta.common.pdf_to_text`. No hay OCR ni reconstrucción de filas multilínea: un PDF escaneado falla con un diagnóstico, y las tablas complejas requieren una tabla/transcripción verificada antes de importarlas.

La opción `file.type` decide el lector; no se cambia de lector por la extensión. No se admiten XLS antiguo, documentos cifrados ni archivos de red.

## 3. Crear el mapeo de la fuente

Copiar `ingesta/mapeos/ejemplo.yaml` a `ingesta/mapeos/<source>.yaml`. El ejemplo está comentado y sus datos son inventados. Usar identificadores en inglés y documentación en español.

El esquema `version: 1` contiene estas claves:

| Clave | Significado |
| --- | --- |
| `source` | `source_id`, `publisher`, `url`, `license`, `region` y `timezone` obligatorios; `id_prefix` opcional |
| `file` | `type` y `header_row` obligatorios; opciones específicas del formato |
| `columns` | Campo de destino → texto exacto de cabecera o posición base uno |
| `date_formats`, `time_formats` | Listas no vacías de formatos `strptime`, por orden de preferencia |
| `defaults` | Valores constantes expresamente establecidos en la respuesta, aplicados solo a celdas vacías o campos sin columna |
| `normalization` | Campo → lista ordenada de transformaciones |
| `values` | Campo → diccionario de sustituciones exactas tras la normalización |
| `slots` | Franja → `start`, `end`, `kind` explícitos |
| `matrix` | Columnas con fechas y marcas explícitas para un calendario |
| `ignore` | Filas físicas y/o coincidencias exactas que deben omitirse |
| `coverage` | Periodo, zonas y opcionalmente ventana horaria que se espera revisar |

Entrecomillar fechas, horas, códigos, códigos postales y región para impedir conversiones implícitas de YAML o pérdida de ceros. `region` es el código INE `01`–`19`: `18` para Ceuta y `19` para Melilla. Declarar `Europe/Madrid` o `Atlantic/Canary` según la respuesta. La fecha de recepción del JSON usa la modificación del fichero local, con zona horaria; la API del parser admite un `retrieved_at` explícito y consciente de zona.

### Campos y formas de expresar el turno

`holder`, `address` y `zone` son obligatorios. Los campos opcionales son `locality`, `postal_code`, `phone`, `duty_phone`, `code` y `nif`. No se exige un código oficial que la respuesta no contenga.

Para una fila por guardia, declarar `date` y elegir **un** modo:

1. `start`, `end` y `kind`, ya sea mediante columnas o constantes documentadas.
2. `slot`, con una definición en `slots` para cada etiqueta posible.

Los tipos admitidos son `diurna`, `nocturna`, `24h`, `localizada` y `refuerzo`. No se deduce el tipo a partir de la duración. Tampoco se convierte automáticamente una etiqueta como «día» en una franja.

Ejemplo de franjas:

```yaml
columns:
  holder: Nombre
  address: Direccion
  zone: Zona
  date: Fecha
  slot: Franja
slots:
  D: {start: '09:00', end: '21:00', kind: diurna}
  N: {start: '22:00', end: '08:00', kind: nocturna}
```

Para una matriz de calendario, conservar las columnas de farmacia y zona, quitar `date`, `slot`, `start`, `end` y `kind` tanto de `columns` como de `defaults`, y declarar fechas y marcas:

```yaml
matrix:
  dates:
    - {column: 'Día 1', date: '01/11/2026'}
    - {column: 'Día 2', date: '02/11/2026'}
  markers: {D: D, N: N}
slots:
  D: {start: '09:00', end: '21:00', kind: diurna}
  N: {start: '22:00', end: '08:00', kind: nocturna}
```

Las fechas de la matriz son completas y explícitas: no se supone el mes ni el año. Una celda vacía no asigna una farmacia; una marca desconocida genera un error con fila y columna. Pueden importarse otras celdas válidas de la misma fila para su revisión, pero el CLI no escribirá una salida con incidencias.

### Normalización, valores por defecto e identidad

Se recortan siempre los espacios exteriores del texto. Las operaciones optativas son `strip`, `spaces` (colapsar espacios), `upper`, `lower`, `title`, `digits` (solo dígitos) y `normalize` (mayúsculas, sin acentos, espacios colapsados; utilidad compartida). Las sustituciones `values` se aplican después; por ejemplo, `kind: {D: diurna}`. Se conserva la etiqueta original de franja o marca en `raw_label`.

Un teléfono presente debe quedar en nueve dígitos y un CP en cinco. Si son inválidos, se conservan como ausentes con un aviso. No se completan ceros ni se inventan teléfonos. Un campo opcional no aportado queda en `None`. Una fecha u hora nativa en una columna de texto incompatible se rechaza.

Los identificadores son `<id_prefix>:<code>`; si falta código, se usa el NIF presente. Si no existen ambos, se deriva una huella reproducible de nombre, dirección, municipio y CP, señalada con `derived-`. Esa clave es técnica, **no un número de farmacia oficial**. Mantener estable `id_prefix` al actualizar una fuente. Si cambia un dato de identidad sin código, cambia la huella; debe revisarse antes de sustituir datos.

`defaults` solo debe recoger constantes respaldadas por la respuesta —por ejemplo, la zona indicada para toda una tabla—. No sirve para tapar un dato ilegible ni para completar una guardia ausente. Las celdas vacías, incluidas las compuestas de espacios, usan ese valor si está declarado.

`ignore.rows` usa números base uno y se aplica por hoja/página. `ignore.equals` es una lista de `{column: Nombre, value: TOTAL}`: basta una coincidencia exacta, recortando espacios exteriores, para omitir la fila. Solo se ignoran automáticamente las filas completamente vacías y las anteriores a la cabecera. No se descartan silenciosamente las filas restantes.

### Fechas y horas

Los formatos de fecha deben expresar día, mes y año completos (también se admiten día del año o semana ISO con año completo). Se prueban en el orden declarado. Es responsabilidad del mapeo resolver convenciones ambiguas como mes/día frente a día/mes. Las horas de 12 horas necesitan `%p`.

Si el fin es igual o anterior al inicio, corresponde al día siguiente, como establece el contrato existente. Se permite `24:00`/`24:00:00` exclusivamente como fin. Los turnos conservan la zona horaria y `times_exact: true`, pues sus límites deben estar expresamente declarados. Las horas locales inexistentes o ambiguas en un cambio horario se rechazan para no escoger un instante sin evidencia. Un turno que atraviesa un cambio horario conserva los offsets correctos en ambos extremos.

## 4. Validar y revisar cobertura

```sh
python -m ingesta.generico --mapeo ingesta/mapeos/<source>.yaml \
  --entrada /ruta/local/respuesta.xlsx --salida data/out/<source>.json --solo-validar
```

También se puede omitir `--salida` con `--solo-validar`. Este modo no crea directorios ni modifica la salida existente.

El resumen JSON en stdout contiene recuentos de farmacias y turnos, cobertura diaria y huecos. Los avisos van a stderr e identifican fichero, hoja/página cuando corresponde, fila y motivo. En matrices también señalan la columna. Los duplicados indican su primera aparición. No se sobrescriben datos contradictorios de una farmacia ni turnos con el mismo identificador, zona, inicio y tipo pero distinto fin.

Para comprobar todo el periodo y todas las zonas de la respuesta, declararlos explícitamente:

```yaml
coverage:
  start: '01/11/2026'
  end: '30/11/2026'
  zones: [Zona Inventada Norte, Zona Inventada Sur]
```

Sin periodo declarado se examina únicamente el intervalo **observado**, identificado mediante `scope: observed`; sin zonas declaradas solo se conocen las que tienen turnos válidos. Por tanto, no puede descubrirse una zona totalmente ausente o días anteriores/posteriores sin declararlos. Los turnos nocturnos cuentan en cada fecha que realmente cubren; el extremo final es exclusivo.

Por defecto, un hueco significa un día/zona sin ningún turno, no la falta de servicio 24 horas. Si la respuesta exige continuidad en una ventana diaria, declarar ambos `daily_start` y `daily_end`. Entonces se calcula la unión de intervalos y se indican las horas sin cobertura; se consideran también los turnos iniciados el día anterior. El periodo debe estar ordenado y no superar diez años. Nunca se crean turnos para cubrir los huecos.

Códigos de salida:

| Código | Resultado |
| --- | --- |
| `0` | Validación limpia; salida escrita si se solicitó importar |
| `1` | Avisos, errores de filas, duplicados, ausencia de turnos válidos o huecos; no se escribe nada |
| `2` | Configuración, lectura o escritura fallida, o argumentos inválidos |

Revisar cada incidencia contra el documento. Corregir el mapeo o pedir aclaración de la respuesta. Un duplicado comprobado puede excluirse mediante una regla explícita de filas; no ignorar filas con errores para aparentar cobertura. No hay una opción de forzar publicación parcial. La API `parse_file` devuelve las filas válidas con avisos para facilitar su revisión; quien la use directamente debe comprobar esos avisos y la cobertura antes de importar.

## 5. Generar y comprobar el JSON

Cuando la validación termine sin incidencias:

```sh
python -m ingesta.generico --mapeo ingesta/mapeos/<source>.yaml \
  --entrada /ruta/local/respuesta.xlsx --salida data/out/<source>.json
```

La escritura es atómica y protege la salida anterior ante errores; no puede sobrescribir la entrada ni el mapeo. El documento generado es compatible con `python -m backend.importer data/out/<source>.json`. Ese último comando modifica la base de datos: ejecutarlo solo en el entorno de integración previsto, después de revisar el resultado. No hace falta cambiar `backend.importer` ni los parsers actuales.

Si se recibe un archivo por provincia u hoja, usar el mismo esquema con un mapeo por unidad de fuente, `source_id` e `id_prefix` exclusivos y estables, y salidas diferentes. Así una importación no sustituye los turnos de otra provincia. No concatenar JSONs ni importar sucesivamente varias provincias con el mismo `source_id`: el importador reemplaza los turnos de esa fuente.

## 6. Añadir tests antes de incorporar una fuente

Crear un documento ficticio mínimo con la misma estructura, su mapeo y los resultados esperados. Nombres, direcciones y teléfonos deben ser inventados. Comprobar fechas, turnos nocturnos, columnas, franjas, errores, huecos, duplicados y ausencia de escritura durante validación. No copiar filas reales de la respuesta.

Los ejemplos reproducibles están en `tests/fixtures/generico/`: XLSX por guardia, CSV con franjas, calendario ODS y PDF tabular. Incluyen errores deliberados; el CLI debe devolver `1` con ellos. `build_fixtures.py` los regenera sin red ni dependencias de hojas. Sus mapeos son específicos de tests. `ingesta/mapeos/ejemplo.yaml` es la plantilla comentada para nuevas fuentes, no una fuente oficial activa.

```sh
python -m unittest discover -s tests -v
python -m pytest backend/tests -q
cd app
flutter pub get --enforce-lockfile
flutter analyze
flutter test
```

Los tests de integración prueban los cuatro formatos contra el importador real del backend, dos veces, en una base SQLite aislada y sin reutilizar coordenadas.

## 7. Integración futura en el workflow — solo descripción

Esta entrega no modifica ni ejecuta workflows, Pages, descargas, geocodificación ni exportaciones de snapshot. Para una incorporación posterior autorizada:

1. Versionar el mapeo revisado y disponer del documento recibido mediante el procedimiento de recepción acordado.
2. Instalar los requisitos de ingesta y Poppler. Los requisitos del backend ya incluyen los de ingesta para que las comprobaciones existentes conozcan PyYAML.
3. Ejecutar el CLI primero con `--solo-validar` y conservar resumen y avisos como evidencia de revisión.
4. Generar `data/out/<source>.json` solo con código de salida `0`; detener la integración ante cualquier incidencia.
5. Incorporar esa salida al proceso de importación existente y ejecutar las suites Python y Flutter antes de aprobar su publicación.

Cualquier cambio posterior de automatización, datos publicados o coordenadas debe revisarse en su propio alcance. No se actualizan URLs existentes, firma, applicationId ni snapshot como efecto del importador genérico.

# Asturias: buscador de guardias GESCOF del COF

Inspección directa realizada el **07/11/2026**, mediante peticiones HTTP reales,
con Python estándar. No se ha supuesto el formulario ni se han deducido rotaciones.
El contexto administrativo aportado para esta tarea es la resolución SUGE/2026/2043,
de 05/11/2026; este adaptador consume el buscador del Colegio, no esa resolución.

## Estado y publicación

**Implementada, desactivada hasta autorización de reutilización.**
No se afirma una licencia abierta. `SourceInfo.license` indica expresamente la
autorización pendiente. `ENABLE_ASTURIAS` vale `false` por defecto; solo el valor
`true` activa el procesamiento. También se rechaza la activación en GitHub Actions.

Las capturas y salidas de una ejecución se guardan en
`data/propuestas/asturias/`, carpeta ya ignorada por Git. **Nunca en `data/out/`**:
el importador habitual no las descubre ni las incorpora a su base de datos.
Además, `scripts/export_snapshot.py` excluye incondicionalmente la fuente
`AS-COF-GESCOF`, incluso si alguien la hubiese importado manualmente. Activar el
flag no levanta este veto de publicación. No se cambia el horario ni el contenido
del workflow «Actualizar guardias».

## URLs y transporte comprobados

- Entrada HTTPS (HTTP 200, sin redirección):
  <https://www.farmasturias.org/GESCOF/cms/Guardias/FarmaciaBuscar.asp?IdMenu=111>.
- Destino exacto del formulario POST:
  <https://www.farmasturias.org/GESCOF/cms/Guardias/FarmaciaBuscar.asp?IdMenu=111&intPagina=1>.
- `https://www.farmasturias.org/robots.txt` y su equivalente HTTP respondieron 200.
  Se usa HTTPS con validación normal de certificados; no hay necesidad de HTTP
  sin TLS. Se recibió una cookie ASP de sesión, pero las consultas POST funcionaron
  sin conservar cookies ni autenticarse.
- Respuesta: `Content-Type: text/html`; la etiqueta `meta` declara UTF-8. Algunos
  menús de la plantilla contienen bytes de otra codificación. Las fichas capturadas
  son UTF-8 y conservan ñ/tildes. Se rechaza un campo de ficha con caracteres de
  sustitución; no se convierte a ciegas todo el documento a Windows-1252.

## Formulario inspeccionado

`form[name=formulario]`, `method=post`,
`action=FarmaciaBuscar.asp?IdMenu=111&intPagina=1`.
El envío usa `application/x-www-form-urlencoded`:

| Campo | Valor/formato observado | Función |
|---|---|---|
| `busqueda` | `1` | Campo oculto |
| `Fecha` | `07/11/2026` | Día en formato DD/MM/AAAA; control de texto readonly con calendario |
| `txtMunicipio` | vacío o código de una opción | Concejo; no es un código INE supuesto |
| `txtLocalidad` | vacío o identificador de una opción | Localidad |
| `btnBuscar` | `Buscar` | Botón submit |

Petición real de todos los concejos del 08/11/2026:

```http
POST /GESCOF/cms/Guardias/FarmaciaBuscar.asp?IdMenu=111&intPagina=1 HTTP/1.1
Host: www.farmasturias.org
User-Agent: farmacias-guardia/0.1 (+https://github.com/Alfonsorm14/farmacias-guardia)
Content-Type: application/x-www-form-urlencoded

busqueda=1&Fecha=08%2F11%2F2026&txtMunicipio=&txtLocalidad=&btnBuscar=Buscar
```

Otras peticiones realizadas al mismo destino y con los mismos campos:

| `Fecha` | `txtMunicipio` | `txtLocalidad` | Fichas recibidas |
|---|---|---|---:|
| 07/11/2026 | `343333002` (ALLER) | vacío | 2 |
| 07/11/2026 | `343333004` (AVILÉS) | vacío | 5 |
| 31/12/2026 | vacío | vacío | 100 |
| 01/01/2027 | vacío | vacío | 97 |
| 31/12/2027 | vacío | vacío | 98 |
| 01/01/2028 | vacío | vacío | 0 |
| 01/01/2030 | vacío | vacío | 0 |
| 01/01/2100 | vacío | vacío | 0 |

También se comprobó que 01/01/2025 y 01/01/2026 devuelven fichas (92 y 98).
El calendario JavaScript real, `GESCOF/Fijos/Includes/cal2.js`, permite navegar
por meses y años; no declara una fecha máxima. Por eso la fecha seleccionable no
es prueba de que haya datos publicados. El límite futuro observado es 31/12/2027;
el adaptador descubre de nuevo el horizonte en cada ejecución, consultando día
a día hasta la primera respuesta vacía, sin crear guardias para esa fecha.
Un `--end` explícito permite continuar una inspección a través de días vacíos.
No se afirma un límite histórico que no se ha recorrido.

## Cobertura y paginación

El formulario contiene **76 opciones no vacías de concejo** y **150 opciones no
vacías de localidad**. Son opciones del buscador, no un censo de municipios:
aparecen «LAS REGUERAS» y «REGUERAS (LAS)» con códigos distintos; dos opciones de
localidad comparten el identificador `116`. No se inventan equivalencias ni se
afirma cobertura de los 78 concejos por el mero número de opciones.

Con ambos filtros vacíos se devuelven juntas todas las fichas publicadas del día.
El GET del 07/11/2026 contiene 98 fichas, **60 etiquetas de concejo y 81 de
localidad**. La consulta filtrada de Avilés coincide con las cinco fichas de ese
concejo en la respuesta global. No es necesario multiplicar peticiones por concejo.

Las respuestas observadas incluyen los comentarios «Inicio de la Paginacion» y
«Fin de la Paginacion», pero no hay enlaces ni controles de página; `intPagina=1`
está en el action del formulario. El adaptador no inventa una página 2: si en el
futuro aparecen enlaces `intPagina=`, detiene el procesamiento para inspeccionarlos.

El informe local `raw/coverage.json` registra todas las fechas efectivamente
capturadas, las fechas vacías y las etiquetas distintas de concejo/localidad.

### Resultado del recorrido completo del 07/11/2026

| Métrica | Resultado verificado |
|---|---|
| Días con fichas, sin huecos | **420**, del **07/11/2026 al 31/12/2027** |
| Primer día sin publicación | **01/01/2028**, respuesta vacía validada, sin turnos generados |
| Concejos/localidades en las respuestas | **62 etiquetas de concejo / 113 localidades** |
| Concejos/localidades con turnos normalizados | **61 / 111** |
| Farmacias identificadas | **362** |
| Turnos normalizados, sin duplicar noches de días contiguos | **39.557** |
| Avisos | **468**: 420 por horario semanal, 47 por festivos sin calendario y 1 por el día vacío |

La diferencia de cobertura es explícita: **CANGAS DE ONÍS** no tiene un intervalo
fechado interpretable con seguridad; las localidades **CANGAS DE ONIS** y
**CANCIENES** quedan sin turnos normalizados. Sus fichas se conservan. No se han
rellenado esos huecos ni los concejos que el buscador no devuelve.
No aparecieron otros errores de campos, codificación ni cabeceras nuevas en
el recorrido completo. Los intervalos nocturnos pueden comenzar el 06/11/2026
o terminar el 01/01/2028 porque la respuesta publica expresamente «ayer» o
«mañana»; eso no amplía el rango de días consultados con fichas.

La activación local generó `data/propuestas/asturias/asturias.json`, validado
además con el contrato de entrada del importador, sin importarlo en la base publicada.

## Estructura HTML y normalización

La fecha figura en `h3.FechaGuardias`; los resultados se agrupan por
`h4.MunicipioGuardias`, `h5.HorarioGuardias` y `h6.LocalidadGuardias`.
Cada `ul.ListadoResultados > li` contiene:

- `span.TituloResultado`: titular.
- `span.ico-localizacion`: dirección con prefijo «Dirección:» y CP final `-NNNNN`.
- `span.ico-telefono`: teléfono principal, prefijo «Teléfono:».
- `span.ico-buscador2`: «Nº Farmacia:» seguido del número estable.
- Texto opcional de guardia no presencial y teléfono de urgencia.

El enlace `VerMapa` no se ejecuta ni se necesita para completar datos ausentes.
Se normalizan espacios y entidades HTML. Identificador `AS:<número de farmacia>`,
región INE `03`, zona igual al concejo publicado y localidad igual a su encabezado.
Se conserva la dirección publicada (incluido su CP final), sin el teléfono.
Teléfonos: nueve dígitos o `None` con aviso; el móvil publicado para urgencias va
en `duty_phone`. Se usa exclusivamente `Europe/Madrid`, con cambio de fecha para
turnos cuyo final horario es anterior o igual al inicio.

El atributo `name` del enlace dentro de `HorarioGuardias` proporciona un intervalo
`HH:MM - HH:MM`. Se conserva el texto de cabecera en `raw_label`. Casos relevantes:

- `09:30 - 09:30`, «hoy ... mañana»: 24 horas desde el día consultado.
- `22:00 - 09:30`, «hoy ... mañana»: nocturna hasta el día siguiente.
- `00:00 - 09:30`, «Desde las 10 de la noche de ayer ...»: **22:00 del día
  anterior**, conforme al texto visible; no se trunca a medianoche.
- `00:00 - 00:00`, «Guardia no presencial»: intervalo publicado de 24 horas,
  tipo `localizada`; no se afirma atención presencial.
- «Las 24 horas»: tipo `24h`.
- «Del viernes al viernes siguiente»: se conserva la farmacia pero se omite el
  turno con aviso, porque no se publican los extremos fechados y el atributo
  `09:00 - 09:00` no describe esa semana. No se extiende la asignación a otros días.
- Cabecera con horario diferente los domingos/festivos: el domingo se interpreta
  como 10:00–22:00, porque el texto publica expresamente ese horario y no hace falta
  conocer fiestas locales. De lunes a sábado se conserva la farmacia pero se omite
  el turno con aviso; el atributo no resuelve si es festivo ni se ha publicado un
  calendario de festivos asociado a la respuesta.

Solo se aceptan las parejas de atributo y cabecera contrastadas en las capturas.
Una pareja nueva conserva la farmacia y emite aviso, pero no genera un turno
suponiendo que el atributo horario basta para interpretarla.

Una respuesta sin datos mantiene el formulario y la fecha solicitada, pero no
contiene cabecera `FechaGuardias` ni listas de resultados. Se valida esa estructura
antes de aceptar una respuesta vacía; se informa `SIN_DATOS`, que no significa
«no hay farmacia de guardia». Un error HTML, una fecha diferente, fichas sin
título reconocido o una nueva paginación producen error, no un resultado vacío.

Cada fecha tiene un único HTML vigente: una nueva descarga reemplaza el día
completo, evitando conservar asignaciones anteriores después de un intercambio.
Si la misma noche aparece como «hoy» y como «ayer» en días contiguos, manda el
grupo completo de farmacias observado más recientemente para ese intervalo y zona.
Los avisos incluyen archivo, página 1 y línea HTML.

## Tres registros reales de referencia

Los tres salen de la [respuesta de entrada del 07/11/2026](https://www.farmasturias.org/GESCOF/cms/Guardias/FarmaciaBuscar.asp?IdMenu=111),
capturada sin modificar en `tests/fixtures/asturias/2026-11-07.html`.
La URL de entrada es móvil: para repetir la consulta de ese día se utiliza el
[destino POST](https://www.farmasturias.org/GESCOF/cms/Guardias/FarmaciaBuscar.asp?IdMenu=111&intPagina=1)
con `busqueda=1&Fecha=07%2F11%2F2026&txtMunicipio=&txtLocalidad=&btnBuscar=Buscar`.

| ID | Titular | Dirección; localidad; concejo | Teléfono | Turno normalizado (Europe/Madrid) |
|---|---|---|---|---|
| AS:183 | RODRIGUEZ-PELAEZ PEÑA, ANA MARIA | AVDA. DE AMERICA 2-33880; POLA DE ALLANDE; ALLANDE | 985807047 | 07/11/2026 00:00 → 08/11/2026 00:00; localizada |
| AS:94 | MENENDEZ FERNANDEZ, ISABEL Y FERNANDEZ GONZALEZ, MODESTO | C/ CONSTITUCION 15-33670; MOREDA; ALLER | 985480856 | 07/11/2026 09:30 → 08/11/2026 09:30; 24h |
| AS:265 | LOPEZ ALAIZ, SILVIA | C/ LLANO PONTE, 32-33402; AVILES; AVILÉS | 985541555 | 07/11/2026 22:00 → 08/11/2026 09:30; nocturna |

El offset de todos esos extremos es `+01:00`. El primer caso conserva expresamente
«Guardia no presencial» en `raw_label`; no se presenta como servicio presencial.

## Uso local y cortesía

```powershell
$env:ENABLE_ASTURIAS='true'
python scripts/run_asturias.py --start 2026-11-07
# Procesar de nuevo las capturas sin red:
python scripts/run_asturias.py --sin-descargas
# Revisar un intervalo explícito (no rellena fechas vacías):
python scripts/run_asturias.py --start 2026-11-07 --end 2026-11-08
# Integración en el procesamiento general, con Asturias en salida separada:
python scripts/actualizar_todo.py --sin-descargas
```

La salida de revisión es `data/propuestas/asturias/asturias.json`, con el mismo
esquema de ingesta que Navarra y Madrid. La activación genera registros locales;
no los importa, geocodifica ni publica. El resto del procesamiento sigue su ruta
habitual. El flag desactivado no añade ninguna petición ni paso al flujo existente.
Si la revisión opcional falla, `actualizar_todo.py` lo informa y continúa con las
fuentes actuales, siguiendo su política existente de aislar fallos de descarga.

`robots.txt` capturado:

```text
User-agent: *
Disallow:/GESCOF/index.asp?idMenu=*&fechatratada=*
```

Esa regla prohíbe la ruta `index.asp` indicada, no `cms/Guardias/FarmaciaBuscar.asp`.
El cliente interpreta comodines `*`, fin `$`, precedencia de reglas y `Crawl-delay`.
Falla de forma cerrada si no puede descargar robots o si este prohíbe el destino.
No sigue redirecciones hacia destinos sin inspeccionar. No hay reintentos automáticos.

Todas las peticiones usan el User-Agent del ejemplo. Hay al menos **1,1 s entre
inicios de peticiones**, con reloj y candado compartidos; se respeta un Crawl-delay
superior si se publica. Como máximo hay cuatro consultas en curso para absorber
la latencia del servidor. Al observar una fecha vacía se dejan de programar
consultas nuevas y se completan las ya iniciadas; se conserva únicamente el
recorrido cronológico hasta el primer día vacío. La anticipación puede consultar
fechas adicionales, pero no crea registros para ellas. Ejecutar
una sola instancia por carpeta de caché.

La caché por SHA-256 incluye URL y cuerpo POST, dura seis horas y también conserva
robots. Una segunda ejecución dentro de esa ventana no repite las consultas.
Los HTML diarios se validan antes de reemplazar las capturas anteriores. Los
errores se propagan; para reanudar se usa el mismo directorio de caché.
Las respuestas HTTP de error se guardan por separado (`cache/*.error`), nunca
como HTML válido ni como día sin datos. La excepción identifica fecha, URL y cuerpo POST.

Durante la validación se observó HTTP 500 al consultar a partir del 26/01/2027
con ocho consultas en curso. Se detuvo el recorrido; una comprobación aislada
del 26/01/2027 respondió 200 con 99 fichas. Esto demuestra que esa fecha era
accesible, pero no identifica con certeza la causa del 500. La implementación
final limita la concurrencia a cuatro y no reintenta automáticamente los errores.

## Fixtures y pruebas

`tests/fixtures/asturias/` contiene respuestas completas reales de 07/11/2026,
08/11/2026, 31/12/2027, 01/01/2028 y robots, con SHA-256 en `sha256.json`.
Las tres últimas respuestas de búsqueda se obtuvieron por POST con filtros vacíos;
la primera es el GET de entrada, que muestra el día actual.

Las capturas no se han editado para fabricar casos. **No se observó un teléfono
principal ausente ni la expresión «Concejo de ...» en esas fichas**: los tests de
robustez crean esas dos mutaciones en memoria y las identifican como tales.
Se prueban identidad, ñ/tildes, teléfonos de urgencia, 24 h, noche desde ayer,
cruce a mañana, respuesta vacía real, cambios de estructura/fecha/paginación,
corrección de asignaciones, robots, caché, frecuencia, flag e aislamiento de salida.
El backend prueba además que una importación manual de Asturias no se exporta.

Comandos de la batería Python completa (Windows: `PYTHONUTF8=1` para las lecturas
UTF-8 existentes que no especifican codificación):

```powershell
$env:PYTHONUTF8='1'
python -m unittest discover -s tests -v
python -m pytest backend/tests -q
```

Resultado final: **88 pruebas de ingesta ejecutadas (87 correctas y 1 omitida)** y
**98 pruebas de backend correctas**, con la base local reconstruida desde los datos
existentes y las coordenadas ya guardadas, sin nuevas consultas de geocodificación.
La omisión es la comparación de Baleares con una copia antigua `v1` que no está
en Git. Se corrigió únicamente el import ausente de `pytest` en dos pruebas
existentes que lo necesitan cuando no hay base local. El backend emite un aviso
de deprecación de Starlette/httpx, ajeno a esta fuente.

Se ejecutó también `scripts/run_asturias.py` con `ENABLE_ASTURIAS=false`: sin red
ni escritura. El snapshot del repositorio conserva la huella SHA-256
`63484d1e66f4f244d983ffa4a70d945d4568088da2e6777b55bc24ffb6117bd3`.
La exportación de la versión anterior y la nueva sobre la misma base real fue
**idéntica byte a byte**, fijando el mismo instante de generación para excluir el
cambio normal de `generated_at`. El test de exportación cubre además una base
con Asturias importada manualmente y confirma que sigue excluida.
`app/assets/snapshot.json`, `data/out`, las fuentes existentes y
`.github/workflows/actualizar.yml` no tienen cambios de datos ni de comportamiento.

## Extensión futura: PDF anual para contraste

El futuro PDF anual de 2026 debe incorporarse como una entrada **separada de
contraste**, sin sustituir `parse_html` ni fusionarse en `parse_dir`. Un comparador
podrá recibir los dos `ParseResult`, cruzar número de farmacia, concejo e intervalo
fechado y emitir discrepancias con referencia a ambas fuentes. El buscador seguirá
siendo primario por sus intercambios frecuentes. Una discrepancia o un hueco no
autoriza a proyectar rotaciones, completar fechas ni modificar automáticamente las
asignaciones publicadas por el buscador. La descarga y el parser del PDF quedan
fuera de esta tarea.

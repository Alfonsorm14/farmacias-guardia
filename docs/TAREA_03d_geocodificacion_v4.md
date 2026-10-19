# Tarea 03d — Geocodificador v4, cierre de la 03c y Sant Antoni

Ejecutor: Claude (directamente, 19/10/2026). Sustituye a las entregas de las Tareas 03b/03c.

## Motivo
La revisión de la 03c (docs/revision_03c.txt) la rechazó: pedanías en el centroide de su municipio
(Cala Millor en el centro de Son Servera, Cañada de Gallego en el de Mazarrón), código de respaldo al
centroide municipal y constantes de coordenadas en geocode.py. Al revisar el código aparecieron además:
- `muni_matches` comparaba por subcadena: "Murcia" aceptaba resultados de "Alhama de Murcia" (la caché
  tenía `muni_centroid:alhamademurcia` con las coordenadas de Murcia).
- Nominatim: cualquier resultado que no fuera edificio se contaba como "calle" (incluidos pueblos).
- CartoCiudad sin código postal: "CALLE MAYOR 10, Murcia" devuelve la Calle Mayor de otra pedanía.
- `clean_address` borraba "BAJO" dentro de palabras ("PLAZA DEL TRABAJO" -> "PLAZA DEL TRA").

## Cambios
- `backend/geocode.py` reescrito (v4). Reglas en la cabecera del módulo y en docs/BACKEND.md §3.
- `backend/importer.py`: también se borra la geocodificación si cambian la localidad o el CP.
- `ingesta/parsers/murcia.py`: el completado de poblaciones truncadas usa los municipios INE y las
  palabras completas del Anexo II, no completa palabras que cierran celda en varias filas y avisa si es
  ambiguo. Corrige 14 localidades que la versión anterior estropeaba ("UNION,LA" -> "UNION,LAS").
- Sant Antoni: `scripts/transcribir_sant_antoni.py` genera `data/raw/baleares/2026/Sant_Antoni.txt`;
  el parser de Baleares la usa cuando el PDF no tiene texto (aviso "TRANSCRIPCION").

## Tests nuevos
- `backend/tests/test_geocode.py`: municipios (sin subcadenas), parseo de direcciones, similitud de vías,
  pistas de núcleo, polígonos y calidad de data/guardias.db (fuentes permitidas, ninguna pedanía en el
  casco, sin puntos compartidos por más de 2, Cala Millor a portal/calle).
- `tests/test_murcia.py`: artículo pospuesto, aviso de truncado ambiguo, `_complete_locality`.
- `tests/test_baleares.py`: 27 zonas; Sant Antoni (365 días, 10 farmacias, 9 de enero sin nocturno).

## Revisión independiente (19/10/2026, noche) y correcciones
Revisor: agente Sonnet en solo lectura. Corregido:
- Navarra/Zaragoza: para cada fecha manda la descarga más reciente que la contiene (una corrección de la
  fuente ya no deja dos farmacias de guardia). Ficheros ilegibles → aviso, no caída. Descargas validadas
  antes de guardarse.
- Geocodificador: similitud de vía en los dos sentidos ("SAN JOSE" ya no casa con "JOSE ANTONIO"),
  candidatos ordenados por calidad del nombre antes que por portal, excepción de núcleo compartido solo
  con el núcleo principal, ritmo de CartoCiudad a ~3 peticiones/s. Reprocesadas todas las farmacias.
- App: copia guardada corrupta → se descarta (escritura atómica y validación de versión); fuentes de un
  solo municipio (Madrid, Zaragoza) no se usan fuera de él; "Aún no hay turnos oficiales publicados para
  esta fecha" cuando la fecha cae fuera de lo publicado; "publicados hasta" por zona; días y horas en hora
  de Madrid aunque el teléfono esté en otra zona; "Ahora" se recalcula al volver a la app.
- Madrid: hora 24:00 tolerada; fecha de descarga determinista. Zaragoza: aviso si el horario no se reconoce.
- Sant Antoni: una banda desconocida que no esté justo bajo la cabecera detiene la transcripción.
  Los días 9 y 12 de enero sin turno nocturno están comprobados en el propio PDF (la fuente no lo publica).

API igualada con la app (20/10/2026): `backend/ambito.py` (fuentes municipales), mensaje "aún no publicado"
y campo `datos_hasta`; los dos endpoints comparten `_query_guardias`. Tests nuevos en backend/tests/test_api.py.

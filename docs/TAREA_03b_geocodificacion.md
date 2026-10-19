# Tarea 03b — Mejora de la geocodificación + limpieza de la API

Ejecutor: Antigravity. Requisito previo: Tarea 02b aplicada y data/out regenerado.
Mismos límites que la Tarea 03 (no tocar ingesta/, data/raw/, tests de ingesta).

## Diagnóstico de Claude (BD actual)
- 46 % de farmacias a precisión "localidad"; en Palma solo 1 de 13 a portal; Murcia ciudad 47 de 110 a localidad.
- Causas: (1) consultas sin municipio en Baleares (locality vacía); (2) direcciones sin normalizar
  ("ESQUINA CALLE…", "esq.", "Nº", "S/N", "CL", "AVDA", "CTRA", "Cl.", "C/"); (3) búsqueda en texto libre.

## Cambios
1. Municipio de consulta:
   - Murcia: locality y código postal; si locality es "X (MUNICIPIO)", usar MUNICIPIO como municipio y X como núcleo.
   - Baleares: locality si existe; si no, derivar de `zones` (campo nuevo del JSON): usar la zona solo si es un
     único municipio reconocible (PALMA y PLATJA DE PALMA -> Palma; zonas compuestas "A-B-C" -> probar cada
     municipio y aceptar el resultado cuya calle exista en él). Guardar el municipio usado en geo_query.
   - Ampliar el importador para guardar `zones` (columna nueva en pharmacies, texto JSON).
2. Normalización de dirección: quitar desde "ESQUINA"/"esq."/"esquina" hasta el final o la coma siguiente;
   quitar "Nº", "S/N", "s/n"; expandir abreviaturas (CL, C/, Cl., CALLE; AVDA, AV, AVENIDA; CTRA, CARRETERA;
   PZA, PL, PLAZA; PSO, PASEO; TRAV, TRAVESIA; URB); separar números pegados ("AVDA.REINO" -> "AVENIDA REINO").
3. Estrategia por farmacia (parar en el primer resultado válido):
   a) CartoCiudad con filtros por municipio y/o código postal si el servicio los admite (verificar en la
      documentación oficial; anotar la URL), tipo portal o calle.
   b) Nominatim en modo estructurado (street, city, postalcode, countrycodes=es), respetando 1 petición/s.
   c) Localidad (como hasta ahora).
   Un resultado de calle/portal solo es válido si su municipio coincide con el esperado.
4. Control de calidad: para cada farmacia geocodificada a calle/portal, calcular la distancia al centroide
   de su municipio; si es > 15 km, marcar como sospechosa en el informe y degradarla a "localidad".
5. Reprocesar SOLO las farmacias con precisión "localidad" o fallidas (la caché evita repetir lo bueno).
   Añadir opción `--recheck` para forzarlo.
6. Informe `tmp/geocode_report.txt`: totales por precisión y región, fallidas, sospechosas, y una muestra
   de 20 farmacias aleatorias a portal/calle con su enlace https://www.openstreetmap.org/?mlat=..&mlon=..#map=18/..
   para revisión manual.

## Limpieza de la API
- Respuesta de /v1/guardias y /v1/guardias/dia: una sola lista `guardias` (quitar `turnos` y `resultados`)
  y claves sin tildes únicamente (`direccion`, `telefono`, `telefono_guardia`).
- `farmacias_sin_coordenadas`: contar solo farmacias con turno activo cuyas `zones` coinciden con las de
  las farmacias cercanas encontradas (no el total nacional).
- Ajustar tests a lo anterior; añadir test de normalización de direcciones con 8 ejemplos reales del informe.

## Criterios de aceptación
- Portal + calle >= 80 % del total; Palma >= 85 %; Murcia (municipio) >= 85 %. Si no se alcanza, el informe
  debe explicar por qué con ejemplos (no forzar resultados).
- 0 farmacias sospechosas sin degradar.
- pytest backend/tests y python -m unittest discover -s tests: todo verde.

# Tarea 03c — Eliminar coordenadas falsas (bloqueante)

Ejecutor: Antigravity. Mismos límites que la Tarea 03.

## Defectos detectados por Claude en data/guardias.db
1. 22 farmacias de Baleares tienen exactamente (39.5696, 2.6502), que es la coordenada de TEST de Palma de la
   Tarea 03, usada como respaldo. Ej.: IB:c4a344cba01c (Cala Ratjada), IB:c4d945d264e8 (Port d'Andratx).
   Una farmacia de Cala Ratjada no puede aparecer en el centro de Palma.
2. Pedanías situadas en el centroide del MUNICIPIO: 29 farmacias en (37.9886, -1.1365) centro de Murcia
   (p.ej. MU:205 La Raya), 13 en (37.6056, -0.9863) centro de Cartagena (MU:302/453 Los Belones,
   MU:458 Los Urrutias, a más de 15 km), y otros grupos (37.6459222, -0.7174696: 12; 37.6712, -1.6988: 9).

## Reglas nuevas (sustituyen a lo anterior donde contradigan)
- Prohibido usar coordenadas fijas, de test o de comunidad como respaldo. Ninguna constante de
  coordenadas en geocode.py salvo las cajas de validación por comunidad.
- Precisión "localidad" = centroide del NÚCLEO de población (la pedanía: "LA RAYA" en "LA RAYA (MURCIA)",
  "CALA RATJADA" en "CALA LLITERAS (CALA RATJADA)", "PORT D'ANDRATX"), geocodificado como lugar habitado
  (CartoCiudad tipo población/entidad o Nominatim place=village/hamlet/suburb/town) y validado:
  debe caer dentro del municipio esperado.
- Si no se puede situar ni la dirección ni el núcleo: lat/lon = NULL, geo_precision = NULL. Nunca el
  centroide del municipio para una pedanía, salvo que la farmacia esté en el casco urbano del municipio
  (locality == municipio).
- Control final: ningún par (lat, lon) compartido por más de 2 farmacias salvo que tengan la misma
  dirección normalizada; listarlos en el informe si los hay.
- API: añadir a cada farmacia `ubicacion_aproximada: true` cuando geo_precision == "localidad".

## Criterios de aceptación
- 0 farmacias en (39.5696, 2.6502) salvo que su dirección real esté ahí (comprobar).
- 0 pedanías con el centroide de su municipio.
- Informe con: totales por precisión, nº con lat/lon NULL (y lista), y la comprobación de puntos compartidos.
- Tests: uno que falle si alguna farmacia tiene coordenadas idénticas a cualquier coordenada usada en
  conftest.py; otro con MU:302 (Los Belones) a menos de 5 km del núcleo de Los Belones.
- pytest backend/tests y python -m unittest discover -s tests en verde.

# Tarea 02b — Corrección de localidades (ingesta Baleares y Murcia)

Ejecutor: OpenCode. Revisión de Claude: la geocodificación falla o cae a "localidad" por defectos en
`locality` que vienen de la ingesta.

## Murcia (`ingesta/parsers/murcia.py`, `_join_fragment`)
Palabras mal unidas al reconstruir celdas partidas en varias líneas. Ejemplos reales:
`LOSALCAZARES`, `TORREPACHECO`, `MOLINA DESEGURA`, `LASTORRES DECOTILLAS`, `ALMENDRIC OS-LORCA`,
`DOLORES-TORRE PACHEC`, `LOS NAREJOS (LOSALCAZARES)`.
Solución exigida: decidir si dos fragmentos se unen con o sin espacio usando un vocabulario de referencia:
1. Los 45 municipios oficiales de la Región de Murcia (lista INE, provincia 30). Incluye la lista como
   constante en el código, con un comentario que cite la fuente (URL del INE consultada).
2. Las palabras que aparecen enteras (sin partir) en cualquier parte del Anexo II.
Regla: unir sin espacio solo si la palabra resultante está en el vocabulario o si el primer fragmento
termina en guion; en cualquier otro caso, con espacio. Si el último fragmento queda truncado
("TORRE PACHEC"), completar solo si hay un único municipio/palabra del vocabulario que lo empiece; si no, warning.
Además: si la localidad lleva el municipio entre paréntesis ("LA PUEBLA (CARTAGENA)"), conservarla tal cual.

## Baleares (`ingesta/parsers/baleares.py`)
1. `locality` es None para la mayoría de farmacias porque la dirección no termina en "- LOCALIDAD".
   NO inventar: dejar `locality` como está, pero añadir al JSON exportado de cada farmacia la lista
   `zones` (zonas de guardia distintas en las que aparece). Esto requiere ampliar `export.py` con un
   campo nuevo y opcional `zones` en las farmacias (cambio de contrato aprobado por Claude; no tocar model.py:
   calcularlo en export a partir de los turnos).
2. Localidades basura: `Frente Ed.Portals Plaza. PORTALS NOUS`, `CALA LLITERAS (CALA RATJADA`,
   `URB. MAIORIS`. Regla: si el tramo final tras " - " contiene un punto seguido de espacio, quedarse con el
   texto posterior al último ". "; cerrar paréntesis desequilibrados; no tratar como localidad prefijos
   "URB." (dejarlo en la dirección y locality None).

## Criterios de aceptación
- Murcia: ninguna localidad del JSON contiene LOSALCAZARES, TORREPACHECO, DESEGURA, DECOTILLAS,
  ALMENDRIC OS; test que recorra todas las localidades y compruebe que cada token está en el vocabulario
  o es una palabra corta conocida (DE, LA, LOS, EL, LAS, DEL), listando los que no.
- MU:460 locality "LOS NAREJOS (LOS ALCAZARES)"; MU:66 locality comienza por "DOLORES" y contiene "TORRE PACHECO".
- Baleares: cada farmacia del JSON trae `zones` no vacío; Palma: la de ALCOVER CASASNOVAS incluye "PALMA".
- Los ids de farmacia no cambian (comparar con data/out/*.json previos: copia antes a *_v1.json).
- Todos los tests pasan; regenerar data/out/baleares_2026.json y murcia_2026.json.

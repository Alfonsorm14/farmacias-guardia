# Decisión pendiente — Murcia: turnos en texto y rotaciones del Anexo III

Preparado el 20/10/2026 (madrugada). Nada de esto está activado: la app y la API siguen mostrando
solo los turnos que el BORM asigna en cuadrante. Fuente: Orden de la Consejería de Salud de
29/12/2025, Plan de Urgencias de Oficinas de Farmacia 2026, BORM nº 301 de 31/12/2025
(NPE A-311225-6468), `data/raw/murcia/2026/BORM_2025_6468.pdf`.

## Situación

- De las 581 farmacias del Anexo II, 287 tienen algún turno cargado y solo 117 tienen turnos todo
  el año (13 zonas con cuadrante de 365 días: Murcia capital y pedanías (3), Cartagena, Campo de
  Cartagena, Lorca, San Javier, Alcantarilla, Alhama, Fuente Álamo, La Manga (2) y Los Alcázares).
- En 33 zonas el Anexo III publica **solo el cuadrante de enero** y una regla del tipo "Rotación por
  días, de modo sucesivo según el orden expuesto, hasta 31/12/2026". Desde el 1 de febrero la app
  dice "Sin datos oficiales para esta fecha" en Mula, Molina de Segura, Cieza, Yecla, Jumilla,
  Totana, Caravaca, Águilas, Mazarrón, Torre Pacheco, La Unión, Bullas, Cehegín, etc.

## A) Asignaciones explícitas en texto (10 farmacias) — recomiendo ACTIVAR

No son deducciones: el boletín nombra la farmacia (o la única de la localidad) y los días.

| Farmacia | Texto del BORM (resumen) | Días 2026 | Horario |
|---|---|---|---|
| MU:383 Albudeite | "urgencia diurna permanente localizada" | 365 | no publicado |
| MU:146 Pliego | "urgencia diurna permanente localizada" | 365 | no publicado |
| MU:198 Almendricos | "urgencia permanente localizado fuera del horario mínimo" | 365 | no publicado |
| MU:422 Aledo | "servicio permanente de urgencia, en sistema localizado" | 365 | no publicado |
| MU:424 Benizar | "servicio de urgencia diurno permanente" | 365 | no publicado |
| MU:433 Isla Plana | domingos y festivos, excepto 1/1 y 25/12 | 64 | no publicado |
| MU:498 La Azohía | sábados y festivos (no domingos), salvo 1-1, 6-1, 1-11, 25-12; domingos de julio a 11/9 | 72 | no publicado |
| MU:493 Ifre-Cañada de Gallego | lista de 26 fechas | 26 | no publicado |
| MU:584 Camposol | 15-7 | 1 | no publicado |
| MU:452 Calabardina | refuerzo de 10 a 21 h, domingos y festivos de julio y agosto | 10 | 10–21 h |

- Los festivos salen de la Resolución de la Dirección General de Trabajo de 7/7/2025 (BORM nº 163,
  17/07/2025, NPE A-170725-3546): 12 fiestas regionales/nacionales y las locales de Cartagena
  (27/3 y 25/9) y Águilas (17/2 y 27/3). Isla Plana y La Azohía se tratan como Cartagena.
- Cada asignación guarda la cita literal del boletín y un test comprueba que está en el PDF; las 26
  fechas de Ifre se contrastan completas. Los festivos usados están transcritos con su referencia en
  `data/raw/murcia/2026/fiestas_laborales_2026.txt` y un test los compara con el código
  (`ingesta/parsers/murcia_explicitos.py`, `tests/test_murcia_propuestas.py`).
- **Decisión 1:** el BORM no publica el horario de la "urgencia diurna". Opciones: (a) cargar el día
  completo marcado "horario orientativo" (como los turnos localizados de Murcia), con el defecto de que
  en "Ahora" a las 3:00 aparecerían como de guardia; (b) mostrarlas solo en las vistas de día (Hoy,
  Mañana...) y no en "Ahora". Recomiendo (b); requiere un pequeño cambio en la app.

## B) Proyección de las rotaciones — recomiendo NO activar (o solo con aviso y sin festivos)

`ingesta/parsers/murcia_rotacion.py` aplica la regla publicada solo si es un ciclo simple: sin
saltos, régimen especial de festivos, turnos dobles ni fines de semana a cargo de otra farmacia, y
con el ciclo completo visible en enero. Las vacaciones del Anexo I se respetan dejando el día sin
turno (el BORM no dice quién sustituye). Resultado:

- **13 zonas proyectables** (949 turnos del 20/10 al 31/12): Molina de Segura (11 farmacias,
  ciclo diario de 11), Cieza (12, diario), Mula (6, diario), Puerto Lumbreras (5, diario) y, por
  semanas, Beniel, Blanca, Moratalla, Caravaca/Barranda, Abanilla, Fortuna, Ojos, Ceutí y Lorquí.
- **20 zonas no proyectables**, cada una con su motivo (Totana "librando una semana", Jumilla
  "turno continuo viernes y sábados", Águilas y Mazarrón con régimen de festivos, Yecla con cambios
  de verano, Archena y Librilla con erratas, etc.).

**Prueba retrospectiva** (el punto clave): en Fuente Álamo, que sí publica el cuadrante anual con
una regla "rotación por semanas, de modo sucesivo" igual de limpia, aplicar el método a enero
acierta 323 de 334 días y **falla en 18-19/3, 1/5, 8-9/6, 14-15/8, 27/8, 12/10, 8/12 y 25/12**:
festivos y algunas vísperas, donde los turnos se intercambian aunque la regla no lo diga. Es la única
agrupación de Murcia con cuadrante anual y regla de ciclo simple, así que la evidencia murciana es una
sola zona. En Baleares (que publica el año entero), repetir el ciclo visible en enero da: 5 de 27 zonas
con ciclo visible; Eivissa y Manacor 100 %, Inca 99 %, Ciutadella 93 % y Platja de Palma (estacional)
26 %. Las dos pruebas se reproducen con `scripts/proyectar_rotaciones_murcia.py`.

Otra incertidumbre: 8 de las 13 zonas proyectables dicen "respetando las vacaciones autorizadas". La
proyección deja sin turno los días de vacaciones de la farmacia a la que le tocaría, pero lo probable
es que el ciclo se desplace a partir de ahí; ninguna prueba retrospectiva cubre ese caso.

Es decir, la proyección sería correcta la mayoría de los días y errónea justo en los festivos,
cuando más se usa la app, mandando a alguien a una farmacia cerrada.

**Decisión 2 (elegir una):**
1. No activar y pedir el cuadrante anual completo: la solicitud de acceso a la Región de Murcia es
   una de las 18 pendientes; el Colegio Oficial de Farmacéuticos lo elabora por delegación (Orden de
   9/12/1998, citada en la propia Orden de 29/12/2025). *Recomendada.*
2. Activar solo fuera de festivos y vísperas, con la etiqueta "Turno deducido de la regla del BORM,
   no publicado día a día: confirma por teléfono" (requiere un pequeño cambio en la app para
   mostrar esa etiqueta).
3. Activar todo con esa etiqueta.

## C) Erratas del propio boletín (informativo)

- Agrupación 37 (Archena): el cuadrante de enero está fechado en 2025 (01/01/2025 a 31/01/2025).
- Agrupación 3 (Librilla): la regla dice "hasta 31/12/2025".
- Agrupación 14 (Los Alcázares): la fila del 31/12/2026 se repite tras un salto de página; el parser
  creaba una subzona "(Rotación" con ese turno duplicado. Corregido el 20/10 (un turno menos, ninguna
  guardia distinta).

## Cómo se activaría

```powershell
.venv\Scripts\python scripts\proyectar_rotaciones_murcia.py   # genera data\propuestas\ (no toca nada)
# A) asignaciones en texto:
copy data\propuestas\murcia_explicitos_2026.json data\out\murcia_2026.json   # incluye las zonas de esas 10 farmacias
.venv\Scripts\python scripts\actualizar_todo.py --sin-descargas
```

Para B) habría que integrar la proyección en el parser (opción 2 o 3) y la etiqueta en la app;
está preparado pero no hecho, a la espera de la decisión.

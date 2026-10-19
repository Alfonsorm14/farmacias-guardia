# Tarea 02 — Parser Murcia (BORM 2025-6468, plan de urgencias 2026)

Lee docs/SPEC.md, AGENTS.md y el código existente de ingesta/ (Tarea 01) antes de empezar.
Reutiliza model.py/export.py; no dupliques utilidades: si algo es común, muévelo a ingesta/common.py.

## Cambio de contrato aprobado por Claude
Añadir a `DutyShift`, al final y con valor por defecto: `times_exact: bool = True`.
Significa: True si la fuente da las horas exactas del turno; False si solo da el día.

## Fuente
`data/raw/murcia/2026/BORM_2025_6468.pdf` (155 págs., texto). Extraer con `pdftotext -layout`.
Cada página trae cabecera/pie del boletín ("Número 301 ... Página NNNNN", "NPE: A-311225-6468"):
eliminarlos antes de parsear (pueden partir una tabla o un bloque en dos).
SourceInfo: source_id "MU-BORM-2026", publisher "Consejería de Salud de la Región de Murcia (BORM nº 301, 31/12/2025)",
url "https://www.borm.es/services/anuncio/ano/2025/numero/6468/pdf?id=840645",
license "Acto administrativo publicado en diario oficial (art. 13 TRLPI)".

### Anexo I — descripción por agrupación (solo como contexto; no hace falta parsearlo entero)
### Anexo II — directorio de farmacias (tabla multilínea)
Cabecera: `ZONA  NOMBRE  Nº F  Nº TLFNO  DIRECCION  POBLACIÓN  C.P.`
Las celdas de NOMBRE, DIRECCION y POBLACIÓN se parten en varias líneas ("ALCANTARIL"+"LA").
Una fila nueva empieza cuando aparece valor en la columna ZONA. Usar las posiciones de columna
de la línea de cabecera (y recalcularlas en cada página, pueden variar) para asignar cada trozo.
Reconstruir: holder, numero (Nº F), phone (9 dígitos), address, locality (POBLACIÓN unida), postal_code.
Id de farmacia: `"MU:" + str(int(numero))`  (p.ej. "MU:431"). Si un número aparece dos veces con datos
distintos -> warning.

### Anexo III — cuadrantes por agrupación. Tres formatos reales:
1. Filas diarias: `01/01/2026     431        Hernández Ros-Moreno Hernández`
   -> un turno kind "24h" para esa fecha y la farmacia MU:431 de la agrupación en curso.
   Puede haber subzonas con título propio dentro de una agrupación (p.ej. "Mazarrón (casco)",
   "Puerto de Mazarrón"): zone = "AGRUPACION 18 (MAZARRON) - Mazarrón (casco)".
   Si un mismo día y subzona tiene 2+ filas, todas son turnos (hay agrupaciones con 2 farmacias/día).
2. Listas fijas: bloque "TURNOS DE URGENCIA 24 HORAS / Todos los días del año (...)" seguido de
   líneas "-   MU-056-F, Nombre" -> un turno 24h por farmacia y por cada día de 2026.
3. Refuerzos: "REFUERZOS DE 9-22 HORAS" + regla de días:
   - "Todos los días del año" -> kind "refuerzo", 09:00-22:00, times_exact True, todos los días.
   - Cualquier otra regla ("de lunes a sábado (excluidos festivos)", etc.) -> NO generar turnos;
     warning "REFUERZO_REGLA_NO_SOPORTADA" con agrupación y texto literal.
Cualquier bloque de Anexo III que no encaje -> warning con agrupación y primeras líneas.

### Horas de los turnos 24h
El BORM no fija la hora de relevo. Para turnos de formato 1 y 2: start = fecha 00:00, end = día
siguiente 00:00, times_exact = False. No inventar otra hora.
Los marcados en Anexo I como "sistema localizado fuera del horario mínimo": kind "localizada" en
lugar de "24h" (asociar por número de agrupación; si no se puede asociar con seguridad, "24h" + warning).

## Entregables
- `ingesta/parsers/murcia.py` con `parse(pdf_path: str) -> ParseResult`.
- `tests/test_murcia.py` sobre el PDF real.
- `scripts/run_murcia.py` -> `data/out/murcia_2026.json` + resumen (farmacias, turnos, warnings por tipo,
  y turnos del 2026-10-18 de las agrupaciones 1, 6 y 18).

## Criterios de aceptación (los comprobará Claude)
- Directorio: MU:45 = RUBIO FERNANDEZ, MARIA; tel 968802950; CL. MAYOR, 87; ALCANTARILLA; 30820.
- MU:534 dirección completa "CALLE MEDICO PEDRO NOGUEROLES, ESQUINA CALLE ANDORRA".
- Agrupación 1, 2026-01-01 -> MU:431; 2026-01-03 -> MU:46.
- Agrupación 6: 8 farmacias 24h todos los días (MU:12, 94, 178, 180, 257, 312, 376, 393).
- Agrupación 2: MU:56 24h todos los días; los refuerzos de lunes a sábado generan warning, no turnos.
- Todo turno del Anexo III referencia una farmacia existente del Anexo II (si no, warning).
- Los tests de Baleares siguen pasando.

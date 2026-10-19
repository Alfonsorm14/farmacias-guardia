# Tarea 01 — Modelo común + parser Baleares (CAIB 2026)

Lee docs/SPEC.md y AGENTS.md antes de empezar.

## Entregables
1. `ingesta/__init__.py`, `ingesta/model.py` (exactamente el contrato de SPEC.md), `ingesta/export.py`.
2. `ingesta/parsers/baleares.py` con `parse_dir(path: str) -> ParseResult` que procese todos los PDF
   de `data/raw/baleares/2026/` (ignorar index.html).
3. `tests/test_baleares.py` con tests sobre los PDF reales (no mocks) y casos sintéticos de líneas.
4. `scripts/run_baleares.py` que escriba `data/out/baleares_2026.json` e imprima un resumen:
   nº farmacias, nº turnos, nº warnings, y los turnos de Palma del 2026-10-18.

## Formato de la fuente (pdftotext -layout), una página = un día de una zona
```
Servei Farmacèutic d'urgència:
PALMA                                   <- zona (línea siguiente a la cabecera)

jueves, 1 de enero de 2026              <- fecha en castellano
                  SERVEI D'URGÈNCIA DIURN de 09:00 a 22:00
ALCOVER CASASNOVAS, R             AV. JOAN MIRÓ, 186 (davant C.Cial. Porto-Pí)-PALMA              971909015
                  SERVEI D'URGÈNCIA NOCTURN de 22:00 a 09:00
...
01/01/2026 - 31/12/2026                                     Página 1 de 364
```
Cabeceras de turno observadas (todas deben soportarse; cualquier otra -> warning):
- `SERVEI D'URGÈNCIA DIURN de HH:MM a HH:MM`            -> kind "diurna"
- `SERVEI D'URGÈNCIA NOCTURN de HH:MM a HH:MM`          -> kind "nocturna" (fin al día siguiente)
- `SERVEI D'URGÈNCIA NOCTURN PALMA de HH:MM a HH:MM`    -> "nocturna"
- `SERVEI D'URGÈNCIA (09:00 - 09:00)`                   -> "24h" (fin 09:00 del día siguiente)

Líneas de farmacia: TITULAR, dirección, teléfono final de 9 dígitos. Casos difíciles reales:
- Titular y dirección separados por un solo espacio cuando el titular es largo:
  `SAGRISTA-FARRE-MATEMALAS C/SON RAPINYA, 31 LOC. 7,8 (Rotonda Colegios)   971609946`
  `RIERA OLIVER, Mª MAGDALENA BATLE ANDREU BURGUERA MUT,9 - SES SALINES   971649144`
  Usar la columna de inicio de dirección dominante en la página (la mayoría de líneas la
  marcan con 2+ espacios). Si la separación es ambigua, conservar la línea completa en `address`,
  `holder` con lo que sea seguro, y añadir warning.
- Teléfono de guardia distinto: `ANTONI MAURA, 1 - SENCELLES   ( telf. guàrdies 678048796 )   971874291`
  -> phone=971874291, duty_phone=678048796; quitar el paréntesis de la dirección.
- La localidad suele ir tras " - " o "-" al final de la dirección (p.ej. "- ALAIOR", "-PALMA",
  "- SANTA PONSA"). Extraerla solo si el patrón es claro; si no, None.
- Una zona puede cubrirse con farmacias de otro municipio (Alaior usa farmacias de Maó de noche):
  `zone` es la zona de la página, la localidad es la de la dirección.
- `Sant_Antoni.pdf` es una imagen escaneada: detectar (pdftotext vacío) -> warning SIN_TEXTO.

## Identificador estable de farmacia
`"IB:" + sha1(normalizar(holder) + "|" + normalizar(dirección sin localidad) + "|" + phone)[:12]`
(normalizar = mayúsculas, sin acentos, espacios colapsados). La misma farmacia en distintos días y
zonas debe dar el mismo id.

## SourceInfo
source_id "IB-CAIB-2026", publisher "Govern de les Illes Balears — Servei d'Ordenació Farmacèutica",
url "https://www.caib.es/sites/ordenaciofarmaceutica/es/guardias_ano_2026/",
license "CC BY-SA (aviso legal caib.es)".

## Criterios de aceptación (los comprobará Claude)
- 26 PDF con texto procesados + 1 warning SIN_TEXTO (Sant Antoni).
- Palma 2026-01-01: 19 farmacias diurnas 09:00-22:00 y 3 nocturnas 22:00-09:00 (fin 2026-01-02).
- Formentera 2026-01-01: 1 turno 24h, TORRES - TORRES, 971322419.
- COSTA AMENGUAL (Sencelles): duty_phone 678048796.
- Ningún turno con start >= end.

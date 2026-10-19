# Tarea 01b — Corrección Baleares: separar titular/dirección por coordenadas

Revisión de Claude sobre la Tarea 01: aprobada salvo un defecto.
`split_holder_address` deja 7 farmacias con el titular truncado (primer token) y la dirección
con el resto del nombre (591 warnings LINEA_AMBIGUA). Ejemplos reales:
- `RIERA OLIVER, Mª MAGDALENA BATLE ANDREU BURGUERA MUT,9 - SES SALINES   971649144`
  -> holder "RIERA OLIVER, Mª MAGDALENA", address "BATLE ANDREU BURGUERA MUT,9", locality "SES SALINES"
- `SASTRE BARCELO, BARTOLOME CL DELS AMETLLERS, 25 - Local 1. CAMPOS   971650662`
  -> holder "SASTRE BARCELO, BARTOLOME", address "CL DELS AMETLLERS, 25 - Local 1. CAMPOS"
- `SAGRISTA-FARRE-MATEMALAS C/SON RAPINYA, 31 LOC. 7,8 (Rotonda Colegios)   971609946`
  -> holder "SAGRISTA-FARRE-MATEMALAS", address "C/SON RAPINYA, 31 LOC. 7,8 (Rotonda Colegios)"
- `AZCARATE HERNANDEZ-PINZON GLOSADOR SEBASTIA VIDAL, sostre, 12-C'AS CONCOS   971839503`
  -> holder "AZCARATE HERNANDEZ-PINZON", address "GLOSADOR SEBASTIA VIDAL, sostre, 12-C'AS CONCOS"
- `MATEO-LLAVADOR (FARMACIA Pere Frances, 23 (Es Pratet)` , `MIQUEL OLIVER - AINA OLIVER ALCUDIA, 16 - POLLENÇA`,
  `TUR-TUR (FCIA. MERCAT VELL) Antoni Palau, 1`.

## Solución exigida
En el PDF la tabla tiene columnas fijas: la dirección empieza siempre en la misma coordenada X.
Usar `pdftotext -bbox-layout` (XHTML con xMin de cada palabra) para estas líneas:
1. Por página, calcular la X de inicio de la columna de dirección a partir de las líneas NO ambiguas
   (xMin de la primera palabra tras el hueco de 2+ espacios). Tolerancia ±2 pt.
2. En las líneas ambiguas, las palabras con xMin >= esa X (menos tolerancia) son dirección; el resto, titular.
3. Mantener `pdftotext -layout` como vía principal; el bbox solo para resolver ambigüedades (o para todo,
   si resulta más simple y los tests siguen pasando). Sin dependencias nuevas (xml.etree de la stdlib).
4. Si aun así no se puede separar: comportamiento actual + warning.

## Criterios de aceptación
- 0 warnings LINEA_AMBIGUA para estas 7 farmacias; los 4 ejemplos anteriores exactamente como se indica.
- Test nuevo para cada ejemplo, con el PDF real.
- Los ids de farmacia cambian para estas 7 (es correcto); los demás deben quedar iguales:
  añadir test que compare los ids de Palma 2026-01-01 (excepto SAGRISTA-FARRE) con los de antes.
- Todos los tests anteriores siguen pasando.

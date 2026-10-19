# Despliegue y actualización de datos — opciones (decisión de Alfonso)

La app funciona sin servidor: lleva dentro una instantánea (`app/assets/snapshot.json`) y, si se
compila con `--dart-define=SNAPSHOT_URL=https://…/snapshot.json`, al arrancar descarga la más
reciente y la guarda en el teléfono. Así basta con publicar un fichero estático actualizado cada día.

## Opción A (recomendada): GitHub Actions + GitHub Pages — coste 0 €
1. Crear un repositorio en GitHub (puede ser privado; Pages en privado exige plan de pago,
   así que lo práctico es un repositorio público: los datos son abiertos y el código no tiene secretos).
2. Subir el proyecto (sin `data/guardias.db`, que se reconstruye; sí `data/geo/coordenadas.json`).
3. Activar Pages con origen "GitHub Actions".
4. El flujo `.github/workflows/actualizar.yml` se ejecuta a diario: descarga Navarra, Zaragoza y
   Madrid, regenera, geocodifica solo lo nuevo, pasa los tests, guarda los cambios y publica
   `https://<usuario>.github.io/<repo>/snapshot.json`.
5. Compilar la app con `--dart-define=SNAPSHOT_URL=` esa dirección.

Ventajas: sin servidor que mantener, sin depender de que tu ordenador esté encendido.
Límite: la app no consulta en tiempo real; ve los datos del último día publicado.

## Opción B: tarea programada en tu ordenador
`scripts/actualizar_todo.py` en el Programador de tareas de Windows (diario). Para que los
teléfonos reciban los datos haría falta igualmente publicar el `snapshot.json` en algún sitio.

## Opción C: backend FastAPI en un servidor (más adelante)
Para escala nacional con muchas fuentes. Requiere hosting (VPS o PaaS) y mantenimiento;
la app ya soporta `--dart-define=API_BASE=https://…`.

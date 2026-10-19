# App Farmacias de guardia (Flutter) — v0.6

Muestra la farmacia de guardia más cercana con datos oficiales: ahora, hoy, mañana y pasado,
o cualquier fecha del calendario, con mapa (OpenStreetMap), botón de llamar y "Cómo llegar". Por ahora cubre las Illes Balears,
la Región de Murcia, Navarra y las ciudades de Madrid y Zaragoza; fuera de ellas avisa de
"Sin datos oficiales para esta zona". Permite buscar cualquier población (geocodificador CartoCiudad).

## Datos
- **Sin servidor (por defecto):** usa `assets/snapshot.json`, generado desde `data/guardias.db`:
  ```powershell
  python scripts/export_snapshot.py
  ```
- **Instantánea publicada:** con `--dart-define=SNAPSHOT_URL=https://…/snapshot.json` la app
  descarga al arrancar la instantánea más reciente y la guarda (ver docs/DESPLIEGUE.md).
- **Con backend:** compilar con `--dart-define=API_BASE=https://servidor` y la app usa
  `/v1/guardias` y `/v1/guardias/dia` (ver docs/BACKEND.md).

Pantalla "Fuentes y privacidad" (menú ⋮): fuentes oficiales con licencia y fecha de descarga, atribución
de OpenStreetMap, CartoCiudad (IGN), Nominatim e IDENA, resumen de privacidad y aviso de app no oficial.
Si el GPS falla, la app vuelve al último lugar elegido a mano (guardado solo en el teléfono).
Si la zona de la farmacia más cercana no tiene turnos publicados para la fecha (p. ej. agrupaciones de
Murcia con solo el cuadrante de enero), la app lo avisa: lo que muestra son guardias de zonas vecinas.

Reglas que respeta (docs/SPEC.md): solo turnos asignados explícitamente por la fuente; si no hay,
"Sin datos oficiales para esta fecha". Las farmacias con ubicación aproximada (centro del núcleo)
llevan la etiqueta "Ubicación aproximada"; las que no se han podido situar aparecen aparte.

## Desarrollo
```powershell
cd app
flutter pub get
flutter test                 # 22 tests (motor sobre la instantánea real, buscador, pantallas y preferencias)
flutter run                  # con el móvil conectado por USB (depuración USB activada)
flutter build apk --release  # build/app/outputs/flutter-apk/app-release.apk
```

## Pendiente antes de publicar en Google Play
- Firma de publicación propia (ahora se firma con la clave de depuración).
- Icono y nombre definitivos; política de privacidad (la ubicación no sale del teléfono en modo
  sin servidor).
- Servidor propio de teselas o proveedor con condiciones de uso para producción (la política de
  tile.openstreetmap.org no admite uso intensivo).

Nota: el objetivo es Android (y más adelante iOS); la versión web no se compila porque la app guarda la instantánea en el almacenamiento del teléfono.

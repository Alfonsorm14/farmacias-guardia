# App Farmacias de guardia (Flutter) — v0.1

Muestra la farmacia de guardia más cercana con datos oficiales: ahora, hoy, mañana y pasado,
con mapa (OpenStreetMap), botón de llamar y "Cómo llegar". Por ahora cubre las Illes Balears
y la Región de Murcia; fuera de ellas avisa de "Sin datos oficiales para esta zona".

## Datos
- **Sin servidor (por defecto):** usa `assets/snapshot.json`, generado desde `data/guardias.db`:
  ```powershell
  python scripts/export_snapshot.py
  ```
- **Con backend:** compilar con `--dart-define=API_BASE=https://servidor` y la app usa
  `/v1/guardias` y `/v1/guardias/dia` (ver docs/BACKEND.md).

Reglas que respeta (docs/SPEC.md): solo turnos asignados explícitamente por la fuente; si no hay,
"Sin datos oficiales para esta fecha". Las farmacias con ubicación aproximada (centro del núcleo)
llevan la etiqueta "Ubicación aproximada"; las que no se han podido situar aparecen aparte.

## Desarrollo
```powershell
cd app
flutter pub get
flutter test                 # 10 tests (motor sobre la instantánea real + pantallas)
flutter run                  # con el móvil conectado por USB (depuración USB activada)
flutter build apk --release  # build/app/outputs/flutter-apk/app-release.apk
```

## Pendiente antes de publicar en Google Play
- Firma de publicación propia (ahora se firma con la clave de depuración).
- Icono y nombre definitivos; política de privacidad (la ubicación no sale del teléfono en modo
  sin servidor).
- Servidor propio de teselas o proveedor con condiciones de uso para producción (la política de
  tile.openstreetmap.org no admite uso intensivo).

# Estado de la auditoría del 27/10/2026

Trabajo completado en el **mismo PR #1**, `codex/auditoria-independiente-2026-10-27`, listo para revisión. Informe: `docs/AUDITORIA_2026-10-27.md`. Base original `511743e5f17ed3112365fa6a16e6a24c1edd8bae`; esta continuación parte de `48473c58c03afc98760d533990b1a51a36ff1091`. No crear otro PR, fusionar ni desplegar sin encargo.

## Completado

- H01–H08 y H13–H17: horarios, integridad de importación, identificación OSM, validación de API/snapshot, refresco de Ahora, accesibilidad, paridad de elegibilidad/conteo, anotación y zoom finito. Se conservan todos sus tests.
- **H10 corregido, autorizado por Alfonso:** exportador valida tablas no vacías, IDs únicos, referencias/fuentes coherentes, índices compactos, tipos y duraciones positivas antes de preparar el destino. Lee en transacción de solo lectura. Temporal en el mismo directorio, flush/fsync, cierre, os.replace y limpieza al fallar; conserva el fichero anterior. 23 regresiones nuevas, incluidas base vacía y fallos de JSON/fsync/replace; CLI inválido sale con error.
- **H09 corregido, autorizado por Alfonso:** workflow con versión Flutter 3.47.8 / Dart 3.13.7 y checksum oficial fijo. Caché del paquete con comprobación SHA-256 en cada ejecución. Después de generar, y antes de commit/publicación, Python y desde app pub get con lockfile, analyze y test. Actions oficiales fijadas por SHA; permisos globales vacíos, actualización solo contents:write, despliegue separado con actions:read/pages:write/id-token:write y needs:actualizar. Horarios, descarga y configuración de Pages intactos. YAML/actionlint y siete simulaciones offline verificadas; no se dispara el actualizador.
- **H11 corregido, autorizado por Alfonso:** docs/PRIVACIDAD.md, pantalla Fuentes y privacidad y HTML público explican cálculo local, ausencia de envío a servidores propios, IP/zona de teselas para el IGN, texto del buscador y apertura de Google Maps a petición del usuario. Borrador de Seguridad de los datos en PUBLICAR_ANDROID.md preparado con las respuestas solicitadas y pendiente de revisión de Alfonso antes de enviarlo a Play. No cambia el comportamiento de la app.

## Validación final

SDK fuera del checkout: `/workspace/work/flutter`. Paquete oficial `https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.47.8-stable.tar.xz`, SHA-256 verificado contra el índice y reutilizado por el workflow: `baf7dcc5a3dbba60fe863bf493a6cf203195621f7786eaa5a1bba02cd0d87dd2`.

Desde `app/`:

```
flutter pub get --enforce-lockfile
flutter analyze
flutter test
```

Resultado: dependencias resueltas sin modificar pubspec/lockfile; análisis sin incidencias; **61 tests OK**. Desde la raíz: `.venv/bin/python -m pytest backend/tests -q` (**97 OK**, un aviso de Starlette/httpx) y `python -m unittest discover -s tests -v` (**71 casos, OK**, un omitido preexistente por copia v1 no versionada). `git diff --check`, actionlint y comprobaciones YAML/bash correctos. Exportación de integración a work: 1.156 farmacias, 63.417 turnos y 189 zonas.

En este entorno: `XDG_CONFIG_HOME=/workspace/work/flutter-config`, `PUB_CACHE=/workspace/work/pub-cache`, `ANALYZER_STATE_LOCATION_OVERRIDE=/workspace/work/dart-state`, `FLUTTER_SUPPRESS_ANALYTICS=true`, `DASH__SUPPRESS_ANALYTICS=true`. TestClient necesita permiso de red para sockets locales; no se consultaron fuentes de guardias. Repetir las suites solo si cambia código. No relajar tests ni añadir dependencias del proyecto sin justificación.

## Pendiente

1. **H12 sigue como propuesta:** resolución Python reproducible y advisories; sin actualizaciones de dependencias en esta sesión.
2. **Alfonso debe revisar y enviar el formulario a Play:** el borrador no implica aprobación de Play. Distingue tratamiento efímero propuesto, ausencia de almacenamiento/cifrado en reposo y HTTPS en tránsito; revisar el tratamiento de los proveedores externos. No enviar formularios ni publicar por esta tarea.
3. **Prueba manual antes de publicar:** contraste, TalkBack y Android real (GPS/permisos, llamada, compartir y navegación). Los tests widget no certifican el teléfono.
4. **Reglas vigentes:** no descargar fuentes ni cambiar sus URLs, configuración de Pages, firma, applicationId, snapshot ni coordenadas. La excepción autorizada se limita al workflow actualizar.yml, export_snapshot.py y los textos de H11. No modificar opciones Murcia A/B, retirar Zaragoza o adoptar despliegues nuevos. Validación estructural del exportador no equivale a demostrar completitud de todas las filas/fechas de una fuente.

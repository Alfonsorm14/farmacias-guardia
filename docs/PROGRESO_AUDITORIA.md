# Estado de la auditoría del 27/10/2026

Continuación completada en el **mismo PR #1**, `codex/auditoria-independiente-2026-10-27`; no crear otro PR. Informe: `docs/AUDITORIA_2026-10-27.md`. Base original `511743e5f17ed3112365fa6a16e6a24c1edd8bae`; continuación sobre `323771217414398f2ce6d216372459a185f5be90`. Se cumplen las condiciones para sacar el PR de borrador; no se fusiona ni se despliega.

## Completado

- Flutter instalado fuera del checkout, `/workspace/work/flutter`, desde la ruta oficial correcta: `https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.47.8-stable.tar.xz`. Dart 3.13.7, compatible con el lockfile. SHA-256 del índice verificado: `baf7dcc5a3dbba60fe863bf493a6cf203195621f7786eaa5a1bba02cd0d87dd2`. Los 404 anteriores eran por ruta incorrecta.
- H08 y los nueve tests Dart anteriores validados. H14: refresco de Ahora en inicio/fin publicado, incluso con lista vacía; reloj inyectado, pausa/reanudación, cancelación y protección ante respuestas antiguas probados. API y snapshot exponen el siguiente cambio, con respaldo de un minuto para APIs anteriores o datos agotados.
- H13: acciones y selector en Wrap; marcadores con Semantics, acción y área 48×48; ficha modal desplazable; tests de texto al 200 % y anchura 320. H17: zoom finito cuando farmacia y usuario coinciden.
- H15: mismo predicado de elegibilidad para lista, conteo y siguientes cambios. Total API conservado y mostrado, incluso sin lista de guardias. Fixture sintético de paridad compartido por Python/Dart con duplicados, días, bordes y cambio histórico de zona. H16: anotación correcta de ternas.
- Corregida la incompatibilidad introducida por el límite de 500 de la API con la petición de 10.000 del generador de paridad. API acotada a 10.000; test de aceptación y rechazo de 10.001. Generador intacto.

## Validación final

Desde `app/`, con el SDK en PATH:

```
flutter pub get --enforce-lockfile
flutter analyze
flutter test
```

Resultado: dependencias resueltas sin modificar pubspec/lockfile; análisis sin incidencias; **60 tests OK**. Desde la raíz: `.venv/bin/python -m pytest backend/tests -q` (**74 OK**, un aviso de Starlette/httpx) y `python -m unittest discover -s tests -v` (**71 casos, OK**, un omitido preexistente por copia v1 de Baleares no versionada). `git diff --check` correcto.

En este entorno se configuraron cachés fuera del home de solo lectura: `XDG_CONFIG_HOME=/workspace/work/flutter-config`, `PUB_CACHE=/workspace/work/pub-cache`, `ANALYZER_STATE_LOCATION_OVERRIDE=/workspace/work/dart-state`, `FLUTTER_SUPPRESS_ANALYTICS=true`, `DASH__SUPPRESS_ANALYTICS=true`. Las herramientas/TestClient necesitan permiso de red del entorno para sus sockets locales, sin consultar fuentes de guardias. Repetir las suites si cambia código; no añadir dependencias ni relajar tests para resolver errores.

## Solo propuestas / decisiones pendientes

1. **H09 y H10: pipeline, solo informe.** Gates Flutter, validación de completitud y exportación atómica: implementación expresamente fuera del alcance. Workflows, Pages y scripts del pipeline siguen intactos.
2. **H11: requiere decisión de Alfonso.** Privacidad de teselas, política y declaraciones de Play; despliegue y access logs. No cambiar Murcia A/B, firma, applicationId ni retirar Zaragoza.
3. **H12: dependencias.** Resolución Python reproducible y contraste de advisories; sin actualizaciones en esta sesión. Flutter resuelve las versiones fijadas y avisa de 21 paquetes con versiones más recientes fuera de restricciones.
4. **Prueba manual antes de publicar.** Contraste, TalkBack y uso real en Android (GPS/permisos, llamadas, compartir, navegación). Los tests widget no certifican estos aspectos del teléfono.

No descargar fuentes ni regenerar `app/assets/snapshot.json`, `data/geo/coordenadas.json` o el fixture de paridad de producción para continuar. Se mantuvieron los datos protegidos y todas las aserciones de tests existentes.

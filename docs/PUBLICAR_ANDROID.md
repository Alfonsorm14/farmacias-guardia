# Publicar la app en Google Play — guía y textos preparados

Preparado el 20/10/2026; actualizado para la **v1.0.0** (candidata a publicación). Nada de esto se ha
hecho todavía: la clave de firma y la cuenta de desarrollador son tuyas y no deben salir de tu ordenador.

**Lista de comprobación antes de subir**
- [ ] Revisar y aprobar la política de privacidad (`web/privacidad.html`; se publica en
      https://alfonsorm14.github.io/farmacias-guardia/privacidad.html con la siguiente ejecución del flujo).
- [ ] Decidir Zaragoza (ver abajo).
- [ ] Probar la APK en un móvil real (permiso de ubicación, "Cómo llegar", llamar, compartir, mapa).
- [ ] Clave de firma y `key.properties` (apartado 1).
- [ ] Cuenta de Play Console, ficha (apartado 4) y formularios (apartado 3).

## 1. Clave de firma (una sola vez, en tu ordenador)

```powershell
cd C:\Users\adoni\dev\farmacias-guardia\app\android
keytool -genkeypair -v -keystore C:\Users\adoni\claves\farmacias-guardia.jks -storetype JKS `
  -keyalg RSA -keysize 2048 -validity 10000 -alias farmacias
```

Crear `app\android\key.properties` (está en `.gitignore`, no se sube nunca):

```
storePassword=<la contraseña del almacén>
keyPassword=<la contraseña de la clave>
keyAlias=farmacias
storeFile=C:\\Users\\adoni\\claves\\farmacias-guardia.jks
```

Guarda una copia del `.jks` y de las contraseñas fuera del ordenador: sin ellas no se pueden publicar
actualizaciones (con "Play App Signing", Google guarda la clave de la app y la tuya es solo de
subida, recuperable a través de soporte, pero mejor no depender de eso).

`app\android\app\build.gradle.kts` ya usa `key.properties` si existe; si no, firma con la clave de
depuración (para pruebas). Comprobado en el contenedor con una clave de prueba desechable.

## 2. Compilar el paquete para Play

```powershell
cd C:\Users\adoni\dev\farmacias-guardia\app
flutter build appbundle --release --dart-define=SNAPSHOT_URL=https://alfonsorm14.github.io/farmacias-guardia/snapshot.json
```

Resultado: `build\app\outputs\bundle\release\app-release.aab`. Antes de cada versión, subir
`version:` en `pubspec.yaml` (ahora `1.0.0+11`; el número tras `+` debe crecer siempre).

## 3. Play Console

- Cuenta de desarrollador (pago único de 25 USD). Según fuentes no oficiales de 2026, las cuentas
  personales nuevas deben pasar una prueba cerrada con al menos 12 testers durante 14 días antes de
  publicar en producción [VERIFICAR en la propia Play Console al crear la cuenta].
- Política de privacidad: URL pública obligatoria (por la ubicación):
  https://alfonsorm14.github.io/farmacias-guardia/privacidad.html (fuente: `web/privacidad.html`, la copia
  el flujo diario a GitHub Pages). La app la enlaza desde "Fuentes y privacidad".
- Permisos: ubicación precisa y aproximada (solo con la app abierta, para buscar la farmacia más
  cercana). No hay ubicación en segundo plano.

### Seguridad de los datos (formulario "Data safety") — borrador pendiente

**Pendiente de revisión de Alfonso antes de enviar a Google Play.** Estas son respuestas propuestas para la versión actual con instantánea; no se ha enviado el formulario. Deben contrastarse con las preguntas vigentes de Play y con el tratamiento de los proveedores externos.

| Pregunta | Respuesta propuesta |
|---|---|
| Datos recogidos | Ubicación precisa: sí, recogida. Declaración conservadora para la funcionalidad de ubicación/mapa; el cálculo de guardias ocurre en el teléfono y no se envía la ubicación a servidores propios. |
| Finalidad | Funcionalidad de la app: búsqueda de farmacias y mapa. |
| Procesamiento efímero | Sí: propuesta de tratamiento efímero de la ubicación, sin almacenarla en servidores propios. Revisar la declaración aplicable al IGN antes de enviarla. |
| ¿Se comparten datos? | No, propuesta. «Cómo llegar» abre Google Maps solo por una acción iniciada por el usuario; revisar la excepción correspondiente de Play. No hay cesión para publicidad ni analítica. |
| ¿Se vincula a la identidad? | No: sin cuentas ni identificadores de seguimiento. |
| Publicidad o analítica | No. |
| Cifrado de datos almacenados | No aplica al almacenamiento de la ubicación: no se almacena en servidores propios. El último lugar elegido manualmente se guarda solo en el teléfono. |
| Cifrado en tránsito | Sí, las comunicaciones de la app usan HTTPS. La ausencia de almacenamiento no elimina el cifrado en tránsito ni justifica marcarlo como inexistente. |
| Cuentas | No hay registro ni cuentas de usuario. |
| Eliminación | No hay ubicación almacenada en servidores propios; los datos locales se pueden borrar desde los ajustes del teléfono o al desinstalar. |

El mapa pide teselas al IGN, que recibe la IP y la zona mostrada. El buscador envía el texto escrito a CartoCiudad (IGN). «Cómo llegar» entrega el destino de la farmacia a Google Maps solo al pulsarlo. Estos hechos y las respuestas propuestas deben revisarse juntos: no se afirma que todos los servicios de terceros descarten sus registros ni que Play haya aceptado esta clasificación.

Si algún día se usa el backend (`API_BASE`), la ubicación sí sale del teléfono hacia el servidor y
el formulario y la política cambian.

**Mapa en producción:** desde la v0.6.3 el mapa usa el Mapa Base de España del IGN (WMTS
`ign-base`, capa `IGNBaseTodo`; sus capacidades declaran "CC BY 4.0 scne.es" y "No se aplican
condiciones" de tasas). Ya no se usa tile.openstreetmap.org, cuya política no admite el tráfico de
una app publicada. Cubre España, que es el ámbito de la app.

### Clasificación de contenido y público
- Cuestionario IARC: sin violencia, sin contenido sensible → apta para todos.
- Público objetivo: mayores de 18 (evita los requisitos de apps infantiles; es una app de servicio).
- Categoría: Medicina (o Salud y bienestar). Contacto: el correo de la cuenta de desarrollador.
- Declaración de apps de salud (formulario "Health apps" de la Play Console) [VERIFICAR qué apartados
  pide para una app informativa sin datos de salud].
- Nivel de API objetivo: `targetSdk` lo fija Flutter (`flutter.targetSdkVersion`); comprobar que cumple
  el mínimo vigente de Google Play al publicar [VERIFICAR].

## 4. Ficha de la tienda (textos)

**Nombre (máx. 30):** Farmacia de guardia cerca (25 caracteres)
*(evitar "oficial" en el nombre: la app no lo es y podría tomarse por suplantación)*

**Descripción breve (máx. 80):** La farmacia de guardia más cercana, con los turnos oficiales publicados.

**Descripción completa:**

> Encuentra la farmacia de guardia más cercana, ahora o para cualquier día, con los turnos que
> publican las administraciones.
>
> • Guardias de ahora, de hoy, de mañana y de cualquier fecha del calendario.
> • Mapa, distancia, botón para llamar y "Cómo llegar".
> • Datos oficiales: Govern de les Illes Balears, Región de Murcia (BORM), Gobierno de Navarra,
>   Ayuntamiento de Madrid y Ayuntamiento de Zaragoza. Cada guardia indica su fuente.
> • Si la fuente oficial no ha publicado los turnos de tu zona o de esa fecha, la app lo dice: no
>   inventa ni deduce turnos.
> • Funciona sin conexión con los últimos datos descargados.
> • Sin registro, sin anuncios y sin seguimiento. La app no envía tu ubicación a ningún servidor propio.
>
> Por ahora cubre Baleares, la Región de Murcia, Navarra y las ciudades de Madrid y Zaragoza; se irán
> añadiendo zonas a medida que las administraciones publiquen sus datos.
>
> Esta app no es oficial ni está vinculada a las administraciones ni a los colegios de farmacéuticos.
> Antes de desplazarte, confirma la guardia por teléfono.

### 4.1. Recursos gráficos reproducibles

Los **44 PNG versionados en `play/capturas/`** sustituyen a las capturas antiguas de
`docs/play/`. Se generan con widgets reales de la app, sin emulador, claves de firma,
GPS, backend, descarga de turnos, geocodificación ni peticiones de red.

| Recurso | Ruta | Tamaño en píxeles |
| --- | --- | --- |
| Teléfono | `play/capturas/telefono/{tema}_{vista}.png` | 1080 × 1920 (9:16) |
| Tablet de 7 pulgadas | `play/capturas/tablet_7/{tema}_{vista}.png` | 1280 × 1920 |
| Tablet de 10 pulgadas | `play/capturas/tablet_10/{tema}_{vista}.png` | 1600 × 2560 |
| Gráfico de funciones | `play/capturas/grafico_funciones_1024x500.png` | 1024 × 500 |
| Icono de la ficha | `play/capturas/icono_512x512.png` | 512 × 512 |

Cada formato incluye los temas `claro` y `oscuro` y estas siete vistas:

1. `01_ahora_lista`: guardias activas y distancias.
2. `02_mapa`: mapa con marcadores y fondo esquemático local.
3. `03_manana`: turnos del día siguiente.
4. `04_detalle`: ficha modal de una farmacia sobre el mapa.
5. `05_selector_lugar`: selector de poblaciones, sin activar GPS ni buscar en red.
6. `06_fuentes`: inicio de «Fuentes y privacidad», con licencias y aviso.
7. `07_privacidad`: la misma pantalla desplazada hasta la política de privacidad.

Por ejemplo: `play/capturas/telefono/claro_01_ahora_lista.png`. Se suben los PNG
correspondientes a cada categoría de dispositivo en Play Console. Los formatos de
captura tienen lados entre 320 y 3840 píxeles y relación de aspecto inferior a 2:1.
Los tamaños lógicos son 432 × 768, 600 × 900 y 800 × 1280, respectivamente; el
renderizado se hace directamente a la resolución final, sin ampliar un PNG pequeño.
Las categorías de tablet son perfiles de captura, no certificaciones de hardware.

**Escenario fijo y privacidad.** Se lee exclusivamente `app/assets/snapshot.json`.
El lugar es el ejemplo público Palma ya definido en la app (39.5696, 2.6502), sin
editar sus coordenadas. El reloj está fijado al **27/10/2026 a las 12:00 de
Europe/Madrid** (`2026-10-27T11:00:00Z`); «Mañana» consulta el 28/10/2026. El test
exige guardias en ambas fechas. Si una futura instantánea deja de cubrir esas
fechas, hay que elegir explícitamente otro escenario con datos y revisar todos los
PNG; el generador falla en vez de inventar turnos.

Un adaptador exclusivo de los tests sustituye, **solo en memoria**, titulares por
«de ejemplo NN», direcciones por «Dirección de demostración» y omite teléfonos.
Conserva turnos, fuentes, distancias y coordenadas. Los PNG llevan un pie de
«Demostración» para no presentar los ejemplos como información vigente. No se
modifica la instantánea ni se incorporan datos personales a estos recursos.

**Mapa sin red.** Los tests interceptan las solicitudes de teselas del IGN y
responden con un PNG local dibujado mediante Canvas. Bloquean cualquier otro
destino. El fondo de calles es esquemático y no corresponde a cartografía real;
se indica en el pie de las capturas de mapa y detalle. Se conservan el widget de
mapa, los marcadores y la atribución de la app. La caché de pruebas es temporal,
de solo lectura y se elimina al terminar. La app normal sigue usando el IGN.
La ficha modal usa el mismo `GuardiaCard`, `SafeArea` y contenedor desplazable que
la app, abierto por el arnés de captura con el reloj fijo para evitar `DateTime.now()`.

**Tipografía y gráfico.** Se cargan explícitamente Roboto Regular, Medium y Bold,
y MaterialIcons desde `bin/cache/artifacts/material_fonts` del SDK Flutter, cuya
ruta se descubre automáticamente en Linux y Windows. No se descargan tipografías
externas ni se usa la fuente de cuadrados de los tests. El gráfico de funciones se
renderiza desde `app/test_capturas/soporte/grafico_play.dart`, con el nombre
«Farmacia de guardia cerca», sin la palabra «oficial». El icono se copia byte por
byte del existente `app/assets/icon/icono_play_512.png`; no se redibuja ni se cambia
el icono de Android.

**Preparación.** Usar Flutter **3.47.8 / Dart 3.13.7** y Python 3. En Linux se
instala como en la auditoría: paquete oficial
`https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.47.8-stable.tar.xz`,
verificado antes de extraer contra el SHA-256 del índice oficial
`https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json`:

```text
baf7dcc5a3dbba60fe863bf493a6cf203195621f7786eaa5a1bba02cd0d87dd2
```

En Windows usar la misma versión estable para Windows y verificar el checksum de
su paquete en el índice oficial correspondiente. El generador no instala SDK ni
paquetes: primero preparar las dependencias, respetando el lockfile:

```sh
cd app
flutter pub get --enforce-lockfile
cd ..
```

**Regenerar desde la raíz del repositorio:**

```sh
bash scripts/generar_capturas.sh
python3 scripts/verificar_capturas.py
```

En PowerShell:

```powershell
.\scripts\generar_capturas.ps1
python scripts/verificar_capturas.py
```

Se pueden definir `FLUTTER_BIN` y `PYTHON_BIN` con las rutas de los ejecutables.
Ambos scripts ejecutan `flutter test --no-pub --dart-define=PLAY_CAPTURAS=true
test_capturas/play_test.dart` y validan todos los PNG. El modo está desactivado sin
esa bandera y no forma parte del arranque de la app ni de la suite normal.
`play/capturas/manifiesto.json` registra dimensiones y SHA-256 de cada archivo.
El validador Python comprueba inventario exacto, integridad PNG, dimensiones y
hashes, sin dependencias adicionales. Los PNG y el manifiesto se versionan juntos.

Para comprobar reproducibilidad, guardar el manifiesto, ejecutar otra vez el script
y comparar ambos: con el mismo SDK, plataforma e instantánea deben coincidir todos
los hashes. Entre sistemas operativos puede haber diferencias de rasterizado;
revisar el cambio visual antes de versionarlo. Abrir **cada PNG** para comprobar
textos, acentos, iconos, ambas paletas y ausencia de desbordes. Tras regenerar:

```sh
cd app
flutter analyze
flutter test
cd ..
python -m unittest discover -s tests -v
python -m pytest backend/tests -q
python scripts/verificar_capturas.py
git diff --check
```

**Validación de estos recursos (27/10/2026, Linux).** Flutter 3.47.8 instalado
desde el paquete oficial y verificado con el SHA-256 anterior; `pub get` con
lockfile intacto, `flutter analyze` sin incidencias y 63 tests normales en verde.
La generación optativa pasa sus 44 comprobaciones. Se han abierto los 44 PNG y
revisado textos, acentos, iconos y desbordes en ambos temas y los tres formatos.
Dos generaciones consecutivas producen los mismos 44 hashes del manifiesto.
Python: 97 tests del backend y 74 casos de unittest en verde (una omisión
preexistente). `bash -n` y el validador de PNG también pasan. El script PowerShell
se ha revisado, pero no se ha ejecutado en Windows en esta sesión.

Instantánea utilizada, conservada sin cambios, SHA-256:

```text
63484d1e66f4f244d983ffa4a70d945d4568088da2e6777b55bc24ffb6117bd3
```

La preparación de estos recursos no publica la app, no ejecuta workflows ni cambia
URLs, Pages, firma, `applicationId`, snapshot o coordenadas.

## 5. Zaragoza: decisión pendiente

El Ayuntamiento de Zaragoza solo publica la guardia del día en curso y zaragoza.es no responde desde
los servidores de GitHub, así que la instantánea diaria no la renueva. La app lo dice con honestidad
("¿Dónde funciona?" → "Sin turnos publicados para estas fechas (los últimos, del …)") y en Zaragoza
muestra "No tenemos los turnos oficiales de esa fecha", pero para la ficha de Play conviene elegir:

1. **Quitar Zaragoza de la publicación** (recomendado para la v1.0): dejar de descargarla y cargarla en
   `scripts/actualizar_todo.py` (y borrar sus turnos de la base) y quitarla de los textos (ficha,
   privacidad, índice web). Lo hago en un momento si lo decides.
2. Descargarla desde tu ordenador cada mañana (tarea programada en Windows que ejecute
   `scripts/descargar_zaragoza.py` y suba el resultado): solo sirve si el ordenador está encendido.
3. Dejarla como está.

La lista de lugares de ejemplo de la app ya no ofrece Zaragoza.

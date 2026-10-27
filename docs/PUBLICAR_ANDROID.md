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

**Capturas (1080×1920, 9:16):** `docs/play/1_palma_ahora.png` … `6_fuentes.png` (Palma y Pamplona de
noche, Madrid, "¿Dónde funciona?", bienvenida, fuentes). Se regeneran con
`flutter test test_capturas/play_test.dart --update-goldens`. El mapa no sale en las capturas (en las
pruebas no hay red para las teselas); si se quiere, hacerla desde el móvil.

**Gráfico destacado (1024×500):** `docs/play/grafico_destacado_1024x500.png`.

**Icono de la ficha (512×512):** `app\assets\icon\icono_play_512.png`.

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

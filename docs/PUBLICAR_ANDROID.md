# Publicar la app en Google Play — guía y textos preparados

Preparado el 20/10/2026. Nada de esto se ha hecho todavía: la clave de firma y la cuenta de
desarrollador son tuyas y no deben salir de tu ordenador.

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
flutter build appbundle --release --dart-define=SNAPSHOT_URL=https://<usuario>.github.io/<repo>/snapshot.json
```

Resultado: `build\app\outputs\bundle\release\app-release.aab`. Antes de cada versión, subir
`version:` en `pubspec.yaml` (ahora `0.6.4+10`; el número tras `+` debe crecer siempre).

## 3. Play Console

- Cuenta de desarrollador (pago único de 25 USD). Según fuentes no oficiales de 2026, las cuentas
  personales nuevas deben pasar una prueba cerrada con al menos 12 testers durante 14 días antes de
  publicar en producción [VERIFICAR en la propia Play Console al crear la cuenta].
- Política de privacidad: URL pública obligatoria (por la ubicación). Borrador en `docs/PRIVACIDAD.md`;
  se puede publicar en GitHub Pages junto a la instantánea.
- Permisos: ubicación precisa y aproximada (solo con la app abierta, para buscar la farmacia más
  cercana). No hay ubicación en segundo plano.

### Seguridad de los datos (formulario "Data safety") — respuestas propuestas

| Pregunta | Respuesta (modo sin servidor, el actual) |
|---|---|
| ¿Recoge o comparte datos de usuario? | Ubicación: se usa en el dispositivo, no se envía a servidores propios. El texto de búsqueda de poblaciones se envía a CartoCiudad (IGN). [Revisar: Google considera "recogida" todo dato que sale del dispositivo, aunque sea a un tercero.] |
| Teselas del mapa | Al ver el mapa, el teléfono pide las teselas al IGN (www.ign.es): recibe la IP y la zona visible (≈ ubicación aproximada). [Revisar cómo declararlo.] |
| ¿Cifrado en tránsito? | Sí (HTTPS: CartoCiudad, instantánea, teselas del IGN). |
| ¿Se puede pedir la eliminación? | No hay datos guardados en servidores; los del teléfono se borran desinstalando. |
| Anuncios | No. |
| Cuentas de usuario | No. |

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

**Capturas:** mínimo 2 de teléfono (vista "Ahora" en Palma, mapa, pantalla de fuentes). Se pueden
hacer desde el móvil con la APK de `app\dist`.

**Icono de la ficha (512×512):** `app\assets\icon\icono_play_512.png`.

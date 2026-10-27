# Política de privacidad

Actualizada el 27 de octubre de 2026 para la versión actual de la app, que usa una instantánea de los turnos oficiales.

Las guardias se calculan en el teléfono. Con tu permiso, la app utiliza la ubicación del GPS o el lugar que elijas para ordenar las farmacias por distancia. **La app no envía tu ubicación a ningún servidor propio.** No necesita una cuenta y no incluye publicidad, analítica ni identificadores de seguimiento.

## Mapa y servicios externos

Para dibujar el mapa, el teléfono pide las imágenes del mapa, llamadas teselas, al Instituto Geográfico Nacional (IGN). El IGN recibe la dirección IP y la zona mostrada. Las peticiones de teselas permiten conocer esa zona, aunque las guardias se calculen en el teléfono.

Si usas el buscador de poblaciones, el texto que escribes se envía a CartoCiudad, un servicio del IGN, para obtener las coordenadas del lugar buscado.

**Cómo llegar abre Google Maps solo cuando lo pides**, al pulsar ese botón. La app entrega a Google Maps el destino de la farmacia, mediante sus coordenadas o su dirección. No abre Google Maps automáticamente al buscar guardias ni al mostrar la lista.

Al usar estos servicios se aplican también las políticas de sus proveedores. Esta app no controla los registros que puedan mantener esos servicios.

## Datos guardados en el teléfono

La posición GPS no se guarda. El último lugar que elijas a mano se guarda solo en el teléfono para poder volver a usarlo si falla el GPS. También se guardan la instantánea de turnos y la preferencia de bienvenida. Puedes borrar esos datos desde los ajustes del teléfono o al desinstalar la app.

La descarga de la instantánea desde GitHub Pages no incluye tu ubicación ni el texto del buscador; como en cualquier petición web, el servicio recibe la dirección IP. Si pulsas Compartir, los datos de la farmacia se entregan a la aplicación que elijas o al portapapeles.

## Publicación y otras versiones

La pantalla Fuentes y privacidad y `web/privacidad.html` explican este mismo comportamiento. La dirección pública enlazada por la app sigue siendo https://alfonsorm14.github.io/farmacias-guardia/privacidad.html. Este cambio de texto no implica publicar una nueva versión ni modificar la configuración de Pages.

El borrador del formulario Seguridad de los datos de Google Play está en `docs/PUBLICAR_ANDROID.md`: Alfonso debe revisarlo antes de enviarlo a Play, incluidos responsable y contacto de la política pública. La variante que se compile con `API_BASE` envía la ubicación al backend para calcular distancias; esa variante necesita una política y una declaración acordes antes de publicarse.

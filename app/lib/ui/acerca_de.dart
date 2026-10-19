import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../data/repository.dart';
import '../models.dart';
import '../tiempo.dart';

const String versionApp = '0.6';

/// Otros datos y servicios que usa la app (atribución obligatoria por sus licencias).
class _Tercero {
  final String titulo;
  final String detalle;
  final String url;
  const _Tercero(this.titulo, this.detalle, this.url);
}

const List<_Tercero> _terceros = [
  _Tercero('Mapa: © colaboradores de OpenStreetMap', 'Datos con licencia ODbL. Teselas de tile.openstreetmap.org.',
      'https://www.openstreetmap.org/copyright'),
  _Tercero('CartoCiudad — Instituto Geográfico Nacional', 'Búsqueda de poblaciones y situación de farmacias. CC BY 4.0.',
      'https://www.cartociudad.es'),
  _Tercero('Nominatim — OpenStreetMap',
      'Situación de algunas farmacias y límites municipales de Madrid y Zaragoza. Datos © colaboradores de OpenStreetMap (ODbL).',
      'https://nominatim.org'),
  _Tercero('IDENA — Gobierno de Navarra', 'Situación de las farmacias de Navarra. Licencia Creative Commons de reconocimiento.',
      'https://idena.navarra.es'),
];

/// Fuentes de los datos, licencias, privacidad y aviso.
class AcercaDePage extends StatefulWidget {
  final GuardiasRepository repositorio;

  const AcercaDePage({super.key, required this.repositorio});

  @override
  State<AcercaDePage> createState() => _AcercaDePageState();
}

class _AcercaDePageState extends State<AcercaDePage> {
  // Una sola carga (en modo API sería una petición por cada reconstrucción de la pantalla).
  late final Future<List<Fuente>> _fuentes = widget.repositorio.fuentes();

  Future<void> _abrir(BuildContext context, String url) async {
    final ok = await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('No se pudo abrir $url')));
    }
  }

  static String _fecha(DateTime d) {
    final m = enMadrid(d);
    return '${m.day}/${m.month}/${m.year}';
  }

  @override
  Widget build(BuildContext context) {
    final estilos = Theme.of(context).textTheme;
    Widget titulo(String t) => Padding(
          padding: const EdgeInsets.fromLTRB(16, 20, 16, 4),
          child: Text(t, style: estilos.titleSmall?.copyWith(color: Theme.of(context).colorScheme.primary)),
        );
    return Scaffold(
      appBar: AppBar(title: const Text('Fuentes y privacidad')),
      body: FutureBuilder<List<Fuente>>(
        future: _fuentes,
        builder: (context, snap) {
          final fuentes = snap.data ?? const <Fuente>[];
          return ListView(
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 16, 16, 0),
                child: Text(
                  'Esta app no es oficial ni está vinculada a las administraciones ni a los colegios de '
                  'farmacéuticos. Muestra los turnos de guardia que publican las fuentes oficiales citadas abajo, '
                  'sin completarlos ni deducirlos. Antes de desplazarte, confirma la guardia por teléfono.',
                ),
              ),
              titulo('Turnos de guardia'),
              if (snap.connectionState != ConnectionState.done)
                const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator())),
              if (snap.hasError)
                const ListTile(leading: Icon(Icons.cloud_off), title: Text('No se han podido cargar las fuentes')),
              for (final f in fuentes)
                ListTile(
                  leading: const Icon(Icons.verified_outlined),
                  title: Text(f.editor),
                  subtitle: Text([
                    f.licencia,
                    if (f.municipal) 'Solo su término municipal',
                    if (f.descargado != null) 'Descargado el ${_fecha(f.descargado!)}',
                  ].join(' · ')),
                  trailing: const Icon(Icons.open_in_new, size: 18),
                  onTap: () => _abrir(context, f.url),
                ),
              titulo('Mapa y localización'),
              for (final t in _terceros)
                ListTile(
                  leading: const Icon(Icons.map_outlined),
                  title: Text(t.titulo),
                  subtitle: Text(t.detalle),
                  trailing: const Icon(Icons.open_in_new, size: 18),
                  onTap: () => _abrir(context, t.url),
                ),
              titulo('Privacidad'),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 0),
                child: Text(
                  '${apiBase.isEmpty ? '• Tu ubicación (GPS) se usa dentro del teléfono para calcular las farmacias más '
                      'cercanas; la app no la envía a ningún servidor propio.' : '• Tu ubicación (o el lugar elegido) se envía '
                      'al servidor de la app para calcular las farmacias más cercanas; no se guarda.'}\n'
                  '• Al ver el mapa, el teléfono descarga de OpenStreetMap las teselas de la zona que se muestra, '
                  'lo que revela esa zona a su servidor.\n'
                  '• Si buscas una población, el texto que escribes se envía a CartoCiudad (IGN) para obtener sus '
                  'coordenadas. El último lugar elegido a mano se guarda solo en el teléfono.\n'
                  '• Sin registro, sin publicidad, sin analítica y sin identificadores de seguimiento.',
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 24, 16, 24),
                child: Text('Versión $versionApp', style: estilos.bodySmall, textAlign: TextAlign.center),
              ),
            ],
          );
        },
      ),
    );
  }
}

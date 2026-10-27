import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import '../location.dart';
import '../models.dart';
import 'guardia_card.dart';

const String urlTeselasIgn =
    'https://www.ign.es/wmts/ign-base?service=WMTS&request=GetTile&version=1.0.0'
    '&layer=IGNBaseTodo&style=default&tilematrixset=GoogleMapsCompatible'
    '&TileMatrix={z}&TileCol={x}&TileRow={y}&format=image/png';
const String atribucionMapa =
    'Mapa base © Instituto Geográfico Nacional (CC BY 4.0 scne.es)';

class MapaGuardias extends StatelessWidget {
  final Ubicacion ubicacion;
  final List<Guardia> guardias;

  /// Texto destacado sobre el mapa (aviso de zona o "sin datos para esta fecha").
  final String? aviso;

  const MapaGuardias({
    super.key,
    required this.ubicacion,
    required this.guardias,
    this.aviso,
  });

  void _showPharmacy(BuildContext context, Guardia guardia) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => SafeArea(
        child: SingleChildScrollView(
          child: GuardiaCard(guardia: guardia, ahora: DateTime.now()),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final yo = LatLng(ubicacion.lat, ubicacion.lon);
    final puntos = [
      for (final g in guardias)
        if (g.farmacia.tieneCoordenadas)
          LatLng(g.farmacia.lat!, g.farmacia.lon!),
    ];
    final color = Theme.of(context).colorScheme.primary;
    final mapa = FlutterMap(
      options: MapOptions(
        initialCameraFit: puntos.isEmpty
            ? null
            : CameraFit.bounds(
                bounds: LatLngBounds.fromPoints([yo, ...puntos]),
                padding: const EdgeInsets.all(48),
                maxZoom: 16,
              ),
        initialCenter: yo,
        initialZoom: 13,
      ),
      children: [
        // Mapa base de España del IGN (WMTS, CC BY 4.0 scne.es, sin tasas): oficial y apto para
        // una app publicada, a diferencia de tile.openstreetmap.org.
        TileLayer(
          urlTemplate: urlTeselasIgn,
          maxNativeZoom: 19,
          userAgentPackageName: 'es.alfonsorivero.farmacias_guardia',
        ),
        MarkerLayer(
          markers: [
            Marker(
              point: yo,
              width: 28,
              height: 28,
              child: const Icon(Icons.my_location, color: Colors.blue),
            ),
            for (final g in guardias)
              if (g.farmacia.tieneCoordenadas)
                Marker(
                  point: LatLng(g.farmacia.lat!, g.farmacia.lon!),
                  width: 48,
                  height: 48,
                  child: Semantics(
                    label: 'Farmacia ${g.farmacia.titular}',
                    button: true,
                    onTap: () => _showPharmacy(context, g),
                    child: ExcludeSemantics(
                      child: GestureDetector(
                        behavior: HitTestBehavior.opaque,
                        onTap: () => _showPharmacy(context, g),
                        child: Icon(
                          Icons.local_pharmacy,
                          color: color,
                          size: 36,
                        ),
                      ),
                    ),
                  ),
                ),
          ],
        ),
        const RichAttributionWidget(
          attributions: [TextSourceAttribution(atribucionMapa)],
        ),
      ],
    );
    if (aviso == null) return mapa;
    return Stack(
      children: [
        mapa,
        Positioned(
          left: 8,
          right: 8,
          top: 8,
          child: Card(
            color: Theme.of(context).colorScheme.tertiaryContainer,
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Row(
                children: [
                  const Icon(Icons.info_outline),
                  const SizedBox(width: 8),
                  Expanded(child: Text(aviso!)),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

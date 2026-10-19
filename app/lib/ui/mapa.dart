import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import '../location.dart';
import '../models.dart';
import 'guardia_card.dart';

class MapaGuardias extends StatelessWidget {
  final Ubicacion ubicacion;
  final List<Guardia> guardias;

  const MapaGuardias({super.key, required this.ubicacion, required this.guardias});

  @override
  Widget build(BuildContext context) {
    final yo = LatLng(ubicacion.lat, ubicacion.lon);
    final puntos = [
      for (final g in guardias)
        if (g.farmacia.tieneCoordenadas) LatLng(g.farmacia.lat!, g.farmacia.lon!),
    ];
    final color = Theme.of(context).colorScheme.primary;
    return FlutterMap(
      options: MapOptions(
        initialCameraFit: puntos.isEmpty
            ? null
            : CameraFit.bounds(bounds: LatLngBounds.fromPoints([yo, ...puntos]), padding: const EdgeInsets.all(48)),
        initialCenter: yo,
        initialZoom: 13,
      ),
      children: [
        TileLayer(
          urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
          userAgentPackageName: 'es.alfonsorivero.farmacias_guardia',
        ),
        MarkerLayer(markers: [
          Marker(point: yo, width: 28, height: 28, child: const Icon(Icons.my_location, color: Colors.blue)),
          for (final g in guardias)
            if (g.farmacia.tieneCoordenadas)
              Marker(
                point: LatLng(g.farmacia.lat!, g.farmacia.lon!),
                width: 40,
                height: 40,
                child: GestureDetector(
                  onTap: () => showModalBottomSheet(
                    context: context,
                    builder: (_) => SafeArea(child: GuardiaCard(guardia: g, ahora: DateTime.now())),
                  ),
                  child: Icon(Icons.local_pharmacy, color: color, size: 36),
                ),
              ),
        ]),
        const RichAttributionWidget(attributions: [TextSourceAttribution('© colaboradores de OpenStreetMap')]),
      ],
    );
  }
}

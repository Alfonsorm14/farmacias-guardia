import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

/// Fondo esquemático, sin cartografía real ni descargas. Las posiciones de los
/// marcadores siguen siendo las originales; este fondo no sirve para orientarse.
Future<Uint8List> createLocalTile({bool dark = false}) async {
  final recorder = ui.PictureRecorder();
  final canvas = Canvas(recorder);
  canvas.drawColor(Color(dark ? 0xFF182820 : 0xFFE8EEE8), BlendMode.src);
  final blocks = Paint()..color = Color(dark ? 0xFF243B2B : 0xFFD4E0D3);
  for (var x = 12; x < 256; x += 64) {
    for (var y = 12; y < 256; y += 64) {
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTWH(x.toDouble(), y.toDouble(), 40, 40),
          const Radius.circular(5),
        ),
        blocks,
      );
    }
  }
  final road = Paint()
    ..color = Color(dark ? 0xFF314638 : 0xFFFFFFFF)
    ..strokeWidth = 12;
  for (var i = 0; i <= 256; i += 64) {
    canvas.drawLine(Offset(i.toDouble(), 0), Offset(i.toDouble(), 256), road);
    canvas.drawLine(Offset(0, i.toDouble()), Offset(256, i.toDouble()), road);
  }
  final picture = recorder.endRecording();
  final image = await picture.toImage(256, 256);
  final data = await image.toByteData(format: ui.ImageByteFormat.png);
  image.dispose();
  picture.dispose();
  return data!.buffer.asUint8List();
}

/// Se renderiza con Flutter y las mismas fuentes locales que las capturas.
class FeatureGraphic extends StatelessWidget {
  final Uint8List icon;
  const FeatureGraphic({super.key, required this.icon});

  @override
  Widget build(BuildContext context) => Material(
    color: const Color(0xFF073E2A),
    child: Padding(
      padding: const EdgeInsets.all(56),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Text(
                  'Farmacia de\nguardia cerca',
                  style: TextStyle(
                    fontFamily: 'Roboto',
                    fontSize: 54,
                    height: 1.08,
                    fontWeight: FontWeight.w700,
                    color: Colors.white,
                  ),
                ),
                const SizedBox(height: 26),
                const Text(
                  'Encuentra tu farmacia\nahora y en los próximos días',
                  style: TextStyle(
                    fontFamily: 'Roboto',
                    fontSize: 25,
                    height: 1.35,
                    color: Color(0xFFC7F3D7),
                  ),
                ),
                const SizedBox(height: 24),
                Row(
                  children: [
                    for (final entry in [
                      (Icons.list_alt, 'Lista'),
                      (Icons.map_outlined, 'Mapa'),
                      (Icons.calendar_month_outlined, 'Calendario'),
                    ]) ...[
                      Icon(entry.$1, color: const Color(0xFF9EE4B8), size: 22),
                      const SizedBox(width: 6),
                      Text(
                        entry.$2,
                        style: const TextStyle(
                          fontFamily: 'Roboto',
                          fontSize: 18,
                          color: Colors.white,
                        ),
                      ),
                      const SizedBox(width: 22),
                    ],
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(width: 24),
          ClipRRect(
            borderRadius: BorderRadius.circular(56),
            child: Image.memory(icon, width: 252, height: 252),
          ),
        ],
      ),
    ),
  );
}

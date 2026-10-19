import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models.dart';
import '../tiempo.dart';

String formatoDistancia(double km) => km < 1 ? '${(km * 1000).round()} m' : '${km.toStringAsFixed(km < 10 ? 1 : 0)} km';

String formatoHorario(Turno t) {
  final ini = enMadrid(t.inicio), fin = enMadrid(t.fin);
  final hora = DateFormat('HH:mm', 'es_ES');
  final dia = DateFormat('EEE d', 'es_ES');
  final mismoDia = ini.year == fin.year && ini.month == fin.month && ini.day == fin.day;
  if (t.tipo == TipoTurno.veinticuatroHoras || fin.difference(ini).inHours >= 24) {
    return '${dia.format(ini)} ${hora.format(ini)} – ${dia.format(fin)} ${hora.format(fin)}';
  }
  return mismoDia
      ? '${dia.format(ini)}, ${hora.format(ini)} – ${hora.format(fin)}'
      : '${dia.format(ini)} ${hora.format(ini)} – ${dia.format(fin)} ${hora.format(fin)}';
}

Uri uriComoLlegar(Farmacia f) {
  if (f.tieneCoordenadas) {
    return Uri.parse('https://www.google.com/maps/dir/?api=1&destination=${f.lat},${f.lon}');
  }
  final q = Uri.encodeComponent('${f.direccion} ${f.localidad ?? ''}');
  return Uri.parse('https://www.google.com/maps/search/?api=1&query=$q');
}

/// Texto para copiar y pegar (WhatsApp, SMS...) con los datos de la guardia.
String textoGuardia(Guardia g) {
  final f = g.farmacia;
  final t = g.turno;
  return [
    'Farmacia de guardia: ${f.titular}',
    [f.direccion, if (f.localidad != null) f.localidad!].join(', '),
    if (f.telefonoParaLlamar != null) 'Tel. ${f.telefonoParaLlamar}',
    '${etiquetaTipo(t.tipo)}: ${formatoHorario(t)}${t.horarioConfirmado ? '' : ' (horario orientativo)'}',
    uriComoLlegar(f).toString(),
  ].join('\n');
}

class GuardiaCard extends StatelessWidget {
  final Guardia guardia;
  final DateTime ahora;

  const GuardiaCard({super.key, required this.guardia, required this.ahora});

  @override
  Widget build(BuildContext context) {
    final f = guardia.farmacia;
    final t = guardia.turno;
    final activa = t.activoEn(ahora.toUtc());
    final tema = Theme.of(context);
    final tel = f.telefonoParaLlamar;
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(child: Text('Farmacia ${f.titular}', style: tema.textTheme.titleMedium)),
                Text(formatoDistancia(guardia.distanciaKm), style: tema.textTheme.labelLarge),
              ],
            ),
            const SizedBox(height: 4),
            Text([f.direccion, if (f.localidad != null) f.localidad!].join(' · ')),
            const SizedBox(height: 6),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: [
                Chip(
                  visualDensity: VisualDensity.compact,
                  avatar: Icon(activa ? Icons.check_circle : Icons.schedule, size: 18),
                  label: Text('${etiquetaTipo(t.tipo)} · ${formatoHorario(t)}'),
                ),
                if (!t.horarioConfirmado)
                  const Chip(visualDensity: VisualDensity.compact, label: Text('Horario orientativo')),
                if (f.ubicacionAproximada)
                  const Chip(visualDensity: VisualDensity.compact, label: Text('Ubicación aproximada')),
              ],
            ),
            Row(
              children: [
                if (tel != null)
                  TextButton.icon(
                    onPressed: () => launchUrl(Uri(scheme: 'tel', path: tel)),
                    icon: const Icon(Icons.call),
                    label: Text(tel),
                  ),
                const Spacer(),
                IconButton(
                  tooltip: 'Copiar datos',
                  icon: const Icon(Icons.copy_outlined),
                  onPressed: () async {
                    await Clipboard.setData(ClipboardData(text: textoGuardia(guardia)));
                    if (context.mounted) {
                      ScaffoldMessenger.maybeOf(context)
                          ?.showSnackBar(const SnackBar(content: Text('Datos de la farmacia copiados')));
                    }
                  },
                ),
                TextButton.icon(
                  onPressed: () => launchUrl(uriComoLlegar(f), mode: LaunchMode.externalApplication),
                  icon: const Icon(Icons.directions),
                  label: const Text('Cómo llegar'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

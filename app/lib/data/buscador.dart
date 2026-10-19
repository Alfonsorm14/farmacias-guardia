/// Búsqueda de poblaciones por nombre con el geocodificador de CartoCiudad (IGN).
///
/// Solo se usa cuando el usuario escribe un lugar a mano; la ubicación GPS nunca
/// se envía a ningún servicio en el modo sin servidor.
library;

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../location.dart';

const _base = 'https://www.cartociudad.es/geocoder/api/geocoder';

class BuscadorLugares {
  final http.Client _cliente;

  BuscadorLugares([http.Client? cliente]) : _cliente = cliente ?? http.Client();

  /// Poblaciones y municipios que coinciden con [texto] (máximo 8).
  Future<List<Ubicacion>> buscar(String texto) async {
    final q = texto.trim();
    if (q.length < 3) return const [];
    final uri = Uri.parse('$_base/candidates').replace(queryParameters: {'q': q, 'limit': '15'});
    final r = await _cliente.get(uri).timeout(const Duration(seconds: 10));
    if (r.statusCode != 200) return const [];
    final lista = jsonDecode(utf8.decode(r.bodyBytes));
    if (lista is! List) return const [];
    final out = <Ubicacion>[];
    for (final it in lista) {
      if (it is! Map) continue;
      final tipo = it['type'];
      if (tipo != 'poblacion' && tipo != 'Municipio' && tipo != 'municipio') continue;
      var lat = (it['lat'] as num?)?.toDouble() ?? 0;
      var lon = (it['lng'] as num?)?.toDouble() ?? 0;
      if (lat == 0 && lon == 0) {
        final punto = await _detalle('${it['id']}', '$tipo');
        if (punto == null) continue;
        (lat, lon) = punto;
      }
      final nombre = (it['poblacion'] ?? it['address'] ?? q).toString();
      final muni = (it['muni'] ?? '').toString();
      final provincia = (it['province'] ?? '').toString();
      final etiqueta = [nombre, if (muni.isNotEmpty && muni != nombre) muni, if (provincia.isNotEmpty) provincia].join(', ');
      out.add(Ubicacion(lat, lon, etiqueta));
      if (out.length >= 8) break;
    }
    return out;
  }

  Future<(double, double)?> _detalle(String id, String tipo) async {
    final uri = Uri.parse('$_base/find').replace(queryParameters: {'id': id, 'type': tipo});
    try {
      final r = await _cliente.get(uri).timeout(const Duration(seconds: 10));
      if (r.statusCode != 200) return null;
      final d = jsonDecode(utf8.decode(r.bodyBytes));
      final lat = (d['lat'] as num?)?.toDouble(), lon = (d['lng'] as num?)?.toDouble();
      if (lat == null || lon == null || (lat == 0 && lon == 0)) return null;
      return (lat, lon);
    } catch (_) {
      return null;
    }
  }
}

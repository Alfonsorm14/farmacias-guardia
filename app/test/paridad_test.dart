import 'dart:convert';
import 'dart:io';

import 'package:farmacias_guardia/data/guardias_engine.dart';
import 'package:farmacias_guardia/tiempo.dart';
import 'package:flutter_test/flutter_test.dart';

/// La app (motor sobre la instantánea) y la API (backend sobre la misma base de datos) deben dar
/// las mismas guardias, el mismo mensaje y el mismo aviso. Casos: scripts/generar_paridad.py.
void main() {
  late GuardiasEngine motor;
  late List<Map<String, dynamic>> casos;

  setUpAll(() {
    motor = GuardiasEngine.desdeJson(jsonDecode(File('assets/snapshot.json').readAsStringSync()) as Map<String, dynamic>);
    casos = (jsonDecode(File('test/fixtures/paridad_api.json').readAsStringSync()) as List).cast<Map<String, dynamic>>();
  });

  test('app y API coinciden en todos los casos', () {
    final fallos = <String>[];
    final fallosTurnos = <String>[];
    String iso(DateTime d) {
      final m = enMadrid(d);
      String dos(int n) => n.toString().padLeft(2, '0');
      final off = m.timeZoneOffset.inHours;
      return '${m.year}-${dos(m.month)}-${dos(m.day)}T${dos(m.hour)}:${dos(m.minute)}:00+${dos(off)}:00';
    }
    for (final c in casos) {
      final lat = (c['lat'] as num).toDouble(), lon = (c['lon'] as num).toDouble();
      final r = c.containsKey('fecha')
          ? () {
              final d = DateTime.parse(c['fecha'] as String);
              return motor.consultar(
                  lat: lat,
                  lon: lon,
                  desde: inicioDiaMadrid(d.year, d.month, d.day),
                  hasta: inicioDiaMadrid(d.year, d.month, d.day + 1));
            }()
          : motor.consultar(lat: lat, lon: lon, desde: DateTime.parse(c['instante'] as String));
      final ids = (r.guardias.map((g) => g.farmacia.id).toSet().toList()..sort());
      final esperado = (c['farmacias'] as List).cast<String>();
      final caso = '${c['lugar']} ${c['fecha'] ?? c['instante']}';
      if (r.cobertura != c['cobertura']) fallos.add('$caso: cobertura ${r.cobertura} != ${c['cobertura']}');
      if (r.mensaje != c['mensaje']) fallos.add('$caso: mensaje "${r.mensaje}" != "${c['mensaje']}"');
      if ((r.aviso != null) != c['aviso']) fallos.add('$caso: aviso ${r.aviso != null} != ${c['aviso']}');
      final turnos = (r.guardias.map((g) => '${g.farmacia.id}|${iso(g.turno.inicio)}|${iso(g.turno.fin)}').toList()..sort());
      final turnosApi = (c['turnos'] as List).cast<String>();
      if (turnos.join(',') != turnosApi.join(',')) {
        fallosTurnos.add('$caso: app ${turnos.where((x) => !turnosApi.contains(x)).take(3).toList()} '
            'API ${turnosApi.where((x) => !turnos.contains(x)).take(3).toList()}');
      }
      if (ids.join(',') != esperado.join(',')) {
        fallos.add('$caso: farmacias app ${ids.length} / API ${esperado.length}: '
            'solo app ${ids.where((i) => !esperado.contains(i)).take(5).toList()}, '
            'solo API ${esperado.where((i) => !ids.contains(i)).take(5).toList()}');
      }
    }
    expect(fallos, isEmpty, reason: fallos.join('\n'));
    expect(fallosTurnos, isEmpty, reason: fallosTurnos.take(20).join('\n'));
    expect(casos.length, greaterThan(100));
  });
}

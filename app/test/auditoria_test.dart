import 'package:farmacias_guardia/data/guardias_engine.dart';
import 'package:farmacias_guardia/tiempo.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> snapshot() => {
  'version': 1,
  'generated_at': '2026-10-27T12:00:00Z',
  'sources': [
    ['TEST', 'Fuente de prueba', 'https://example.org', 'Prueba']
  ],
  'pharmacies': [
    ['TEST:1', 'Prueba', 'Calle 1', 'Localidad', null, null, 40.0, -3.0, 'portal', 0]
  ],
  'zones': ['ZONA'],
  'shifts': [[0, 0, 100, 200, 'n', 1]],
};

void main() {
  for (final key in ['sources', 'pharmacies', 'zones', 'shifts']) {
    test('rechaza una actualización vacía en $key', () {
      final data = snapshot()..[key] = [];
      expect(() => GuardiasEngine.desdeJson(data), throwsFormatException);
    });
  }

  for (final shift in [[0, 0, 200, 100, 'n', 1], [-1, 0, 100, 200, 'n', 1], [0, 1, 100, 200, 'n', 1]]) {
    test('rechaza referencias y duraciones inválidas: $shift', () {
      final data = snapshot()..['shifts'] = [shift];
      expect(() => GuardiasEngine.desdeJson(data), throwsFormatException);
    });
  }

  test('instantes en el inicio y fin usan intervalo semiabierto', () {
    final motor = GuardiasEngine.desdeJson(snapshot());
    for (final (minute, expected) in [(99, 0), (100, 1), (199, 1), (200, 0)]) {
      final result = motor.consultar(
        lat: 40, lon: -3,
        desde: DateTime.fromMillisecondsSinceEpoch(minute * 60000, isUtc: true),
      );
      expect(result.guardias.length, expected);
    }
  });

  test('medianoches de Madrid: cambios de hora y fin de año', () {
    for (final (year, month, day, hours) in [(2026, 10, 25, 25), (2027, 3, 28, 23), (2026, 12, 31, 24)]) {
      final start = inicioDiaMadrid(year, month, day);
      final end = inicioDiaMadrid(year, month, day + 1);
      expect(end.toUtc().difference(start.toUtc()).inHours, hours);
    }
  });
}

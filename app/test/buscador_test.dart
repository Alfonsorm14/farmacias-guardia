import 'dart:convert';

import 'package:farmacias_guardia/data/buscador.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('busca poblaciones y completa coordenadas con find', () async {
    final cliente = MockClient((req) async {
      if (req.url.path.endsWith('/candidates')) {
        return http.Response(
            jsonEncode([
              {'id': '1', 'type': 'poblacion', 'poblacion': 'Tudela', 'muni': 'Tudela', 'province': 'Navarra', 'lat': 0.0, 'lng': 0.0},
              {'id': '2', 'type': 'callejero', 'address': 'CALLE TUDELA', 'lat': 0.0, 'lng': 0.0},
            ]),
            200);
      }
      expect(req.url.queryParameters['id'], '1');
      return http.Response(jsonEncode({'lat': 42.06, 'lng': -1.60}), 200);
    });
    final r = await BuscadorLugares(cliente).buscar('Tudela');
    expect(r, hasLength(1));
    expect(r.first.etiqueta, 'Tudela, Navarra');
    expect(r.first.lat, closeTo(42.06, 1e-9));
  });

  test('textos cortos no consultan', () async {
    final cliente = MockClient((_) async => fail('no debe llamar'));
    expect(await BuscadorLugares(cliente).buscar('ab'), isEmpty);
  });
}

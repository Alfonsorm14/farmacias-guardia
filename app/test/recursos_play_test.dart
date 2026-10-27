import 'dart:io';
import 'dart:typed_data';

import 'package:farmacias_guardia/data/repository.dart';
import 'package:farmacias_guardia/models.dart';
import 'package:flutter_test/flutter_test.dart';

import '../test_capturas/soporte/escenario_play.dart';

class MemoryRepository extends SnapshotRepository {
  final ResultadoGuardias result;
  MemoryRepository(this.result);
  @override
  Future<ResultadoGuardias> ahora(
    double lat,
    double lon,
    DateTime instante,
  ) async => result;
  @override
  Future<ResultadoGuardias> dia(double lat, double lon, DateTime dia) async =>
      result;
}

void main() {
  test(
    'anonimiza todas las fichas sin alterar turnos, distancias ni coordenadas',
    () async {
      const source = Fuente(
        id: 'prueba',
        editor: 'Fuente de prueba',
        url: '',
        licencia: 'Prueba',
      );
      const pharmacy = Farmacia(
        id: 'sintetica',
        titular: 'Titular sintético',
        direccion: 'Calle de prueba',
        telefono: '000000000',
        telefonoGuardia: '000000001',
        localidad: 'Localidad de prueba',
        lat: 40,
        lon: -3,
        precision: 'portal',
        fuente: source,
      );
      final shift = Turno(
        tipo: TipoTurno.diurna,
        inicio: captureInstant,
        fin: captureInstant.add(const Duration(hours: 1)),
        zona: 'Prueba',
        horarioConfirmado: true,
      );
      final original = ResultadoGuardias(
        cobertura: true,
        guardias: [
          Guardia(farmacia: pharmacy, turno: shift, distanciaKm: 1.25),
        ],
        sinCoordenadas: [pharmacy],
        totalSinCoordenadas: 1,
        proximoCambio: shift.fin,
        datosHasta: shift.fin,
        aviso: 'Aviso de prueba',
      );
      final repository = CaptureRepository(MemoryRepository(original));
      for (final result in [
        await repository.ahora(40, -3, captureInstant),
        await repository.dia(40, -3, captureInstant),
      ]) {
        for (final f in [
          result.guardias.single.farmacia,
          result.sinCoordenadas.single,
        ]) {
          expect(f.titular, 'de ejemplo 01');
          expect(f.direccion, 'Dirección de demostración');
          expect(f.telefono, isNull);
          expect(f.telefonoGuardia, isNull);
          expect(
            [f.id, f.localidad, f.lat, f.lon, f.precision, f.fuente],
            [pharmacy.id, pharmacy.localidad, 40, -3, 'portal', source],
          );
        }
        expect(result.guardias.single.turno, same(shift));
        expect(result.guardias.single.distanciaKm, 1.25);
        expect(result.proximoCambio, original.proximoCambio);
        expect(result.datosHasta, original.datosHasta);
        expect(result.aviso, original.aviso);
        expect(result.numeroSinCoordenadas, 1);
        expect(result.cobertura, isTrue);
      }
      expect(pharmacy.titular, 'Titular sintético');
      expect(pharmacy.telefono, '000000000');
    },
  );

  test(
    'la red de capturas solo entrega la tesela local y bloquea otros destinos',
    () async {
      final tile = Uint8List.fromList([1, 2, 3]);
      final network = CaptureHttpOverrides(tile);
      await HttpOverrides.runWithHttpOverrides(() async {
        final client = HttpClient();
        final request = await client.getUrl(
          Uri.parse('https://www.ign.es/wmts/ign-base'),
        );
        final response = await request.close();
        expect(await response.expand((bytes) => bytes).toList(), tile);
        expect(network.requests, 1);
        await expectLater(
          client.getUrl(Uri.parse('https://example.org')),
          throwsStateError,
        );
        await expectLater(
          client.openUrl('POST', Uri.parse('https://www.ign.es/wmts/ign-base')),
          throwsStateError,
        );
        expect(network.requests, 1);
        client.close();
      }, network);
    },
  );
}

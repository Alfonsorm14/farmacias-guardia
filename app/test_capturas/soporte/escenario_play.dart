// Adaptadores exclusivos de las capturas: nunca se importan desde lib/.
import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:farmacias_guardia/data/repository.dart';
import 'package:farmacias_guardia/models.dart';

final captureInstant = DateTime.parse('2026-10-27T11:00:00Z');

/// Conserva turnos, fuentes, distancias y coordenadas del snapshot. Oculta los
/// datos identificativos únicamente en memoria antes de construir los widgets.
class CaptureRepository implements GuardiasRepository {
  final GuardiasRepository original;
  final _labels = <String, String>{};
  CaptureRepository(this.original);

  Farmacia anonymize(Farmacia f) => Farmacia(
    id: f.id,
    titular: _labels.putIfAbsent(
      f.id,
      () => 'de ejemplo ${(_labels.length + 1).toString().padLeft(2, '0')}',
    ),
    direccion: 'Dirección de demostración',
    localidad: f.localidad,
    lat: f.lat,
    lon: f.lon,
    precision: f.precision,
    fuente: f.fuente,
  );

  ResultadoGuardias _anonymize(ResultadoGuardias result) => ResultadoGuardias(
    cobertura: result.cobertura,
    mensaje: result.mensaje,
    guardias: [
      for (final g in result.guardias)
        Guardia(
          farmacia: anonymize(g.farmacia),
          turno: g.turno,
          distanciaKm: g.distanciaKm,
        ),
    ],
    sinCoordenadas: result.sinCoordenadas.map(anonymize).toList(),
    totalSinCoordenadas: result.totalSinCoordenadas,
    proximoCambio: result.proximoCambio,
    datosHasta: result.datosHasta,
    aviso: result.aviso,
  );

  @override
  Future<ResultadoGuardias> ahora(
    double lat,
    double lon,
    DateTime instante,
  ) async => _anonymize(await original.ahora(lat, lon, instante));
  @override
  Future<ResultadoGuardias> dia(double lat, double lon, DateTime dia) async =>
      _anonymize(await original.dia(lat, lon, dia));
  @override
  Future<List<Fuente>> fuentes() => original.fuentes();
  @override
  Future<List<Cobertura>> cobertura(DateTime ahora) =>
      original.cobertura(ahora);
  @override
  String get descripcionDatos => original.descripcionDatos;
}

/// Devuelve exclusivamente la tesela local para el mapa. Toda otra petición
/// falla: el modo captura no puede contactar con IGN, GPS, API ni buscadores.
class CaptureHttpOverrides extends HttpOverrides {
  final Uint8List tile;
  int requests = 0;
  CaptureHttpOverrides(this.tile);
  @override
  HttpClient createHttpClient(SecurityContext? context) => _LocalClient(this);
}

class _LocalClient implements HttpClient {
  final CaptureHttpOverrides owner;
  _LocalClient(this.owner);
  @override
  Future<HttpClientRequest> openUrl(String method, Uri url) async {
    if (method != 'GET' ||
        url.host != 'www.ign.es' ||
        url.path != '/wmts/ign-base') {
      throw StateError('Red deshabilitada en capturas: $method ${url.host}');
    }
    owner.requests++;
    return _LocalRequest(owner.tile);
  }

  @override
  Future<HttpClientRequest> getUrl(Uri url) => openUrl('GET', url);
  @override
  void close({bool force = false}) {}
  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

class _LocalHeaders implements HttpHeaders {
  @override
  List<String>? operator [](String name) => null;
  @override
  void forEach(void Function(String name, List<String> values) action) {
    action('content-type', ['image/png']);
    action('cache-control', ['public, max-age=86400']);
    action('age', ['0']);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

class _LocalRequest implements HttpClientRequest {
  final Uint8List tile;
  _LocalRequest(this.tile);
  @override
  final HttpHeaders headers = _LocalHeaders();
  @override
  Future<void> addStream(Stream<List<int>> stream) async {
    await stream.drain<void>();
  }

  @override
  Future<HttpClientResponse> close() async => _LocalResponse(tile);
  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

class _LocalResponse extends Stream<List<int>> implements HttpClientResponse {
  final Uint8List tile;
  _LocalResponse(this.tile);
  @override
  int get statusCode => HttpStatus.ok;
  @override
  int get contentLength => tile.length;
  @override
  bool get isRedirect => false;
  @override
  String get reasonPhrase => 'OK';
  @override
  bool get persistentConnection => false;
  @override
  List<RedirectInfo> get redirects => const [];
  @override
  final HttpHeaders headers = _LocalHeaders();
  @override
  HttpClientResponseCompressionState get compressionState =>
      HttpClientResponseCompressionState.notCompressed;
  @override
  StreamSubscription<List<int>> listen(
    void Function(List<int>)? onData, {
    Function? onError,
    void Function()? onDone,
    bool? cancelOnError,
  }) => Stream<List<int>>.value(tile).listen(
    onData,
    onError: onError,
    onDone: onDone,
    cancelOnError: cancelOnError,
  );
  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

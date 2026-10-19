/// Acceso a los datos: instantánea local (por defecto) o API del backend.
///
/// Si la app se compila con `--dart-define=API_BASE=https://...` usa la API;
/// si no, la instantánea `assets/snapshot.json` incluida en la app.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

import '../models.dart';
import 'guardias_engine.dart';

const String apiBase = String.fromEnvironment('API_BASE');
const double radioPorDefectoKm = 25;

abstract class GuardiasRepository {
  /// Guardias activas en [instante].
  Future<ResultadoGuardias> ahora(double lat, double lon, DateTime instante);

  /// Guardias que se solapan con el día natural [dia] (hora local).
  Future<ResultadoGuardias> dia(double lat, double lon, DateTime dia);

  /// Texto sobre la vigencia de los datos.
  String get descripcionDatos;

  static GuardiasRepository crear() =>
      apiBase.isEmpty ? SnapshotRepository() : ApiRepository(apiBase);
}

DateTime inicioDelDia(DateTime d) => DateTime(d.year, d.month, d.day);

class SnapshotRepository implements GuardiasRepository {
  GuardiasEngine? _engine;
  Future<GuardiasEngine>? _cargando;
  final http.Client _cliente;

  /// URL opcional de una instantánea publicada (p. ej. GitHub Pages) que la app
  /// descarga al arrancar si es más reciente que la incluida o la guardada.
  final String snapshotUrl;

  SnapshotRepository([GuardiasEngine? engine, http.Client? cliente, String? url])
      : _engine = engine,
        _cliente = cliente ?? http.Client(),
        snapshotUrl = url ?? const String.fromEnvironment('SNAPSHOT_URL');

  Future<File?> _ficheroCache() async {
    try {
      final dir = await getApplicationSupportDirectory();
      return File('${dir.path}/snapshot.json');
    } catch (_) {
      return null; // web o tests sin path_provider
    }
  }

  static DateTime _fecha(String texto) {
    final m = RegExp(r'"generated_at":"([^"]+)"').firstMatch(texto);
    return m == null ? DateTime.fromMillisecondsSinceEpoch(0) : DateTime.parse(m.group(1)!);
  }

  Future<GuardiasEngine> _motor() {
    if (_engine != null) return Future.value(_engine!);
    return _cargando ??= () async {
      var texto = await rootBundle.loadString('assets/snapshot.json');
      final cache = await _ficheroCache();
      if (cache != null && await cache.exists()) {
        final guardado = await cache.readAsString();
        if (_fecha(guardado).isAfter(_fecha(texto))) texto = guardado;
      }
      final motor = await compute(_decodificar, texto);
      _engine = motor;
      unawaited(_actualizar(motor.generado));
      return motor;
    }();
  }

  /// Descarga una instantánea más reciente y la usa a partir de la siguiente consulta.
  Future<void> _actualizar(DateTime actual) async {
    if (snapshotUrl.isEmpty) return;
    try {
      final r = await _cliente.get(Uri.parse(snapshotUrl)).timeout(const Duration(seconds: 30));
      if (r.statusCode != 200) return;
      final texto = utf8.decode(r.bodyBytes);
      if (!_fecha(texto).isAfter(actual)) return;
      final motor = await compute(_decodificar, texto);
      _engine = motor;
      final cache = await _ficheroCache();
      await cache?.writeAsString(texto);
    } catch (_) {
      // Sin conexión: se sigue con los datos que hay.
    }
  }

  static GuardiasEngine _decodificar(String texto) =>
      GuardiasEngine.desdeJson(jsonDecode(texto) as Map<String, dynamic>);

  @override
  Future<ResultadoGuardias> ahora(double lat, double lon, DateTime instante) async =>
      (await _motor()).consultar(lat: lat, lon: lon, desde: instante, radioKm: radioPorDefectoKm);

  @override
  Future<ResultadoGuardias> dia(double lat, double lon, DateTime dia) async {
    final inicio = inicioDelDia(dia);
    final fin = DateTime(inicio.year, inicio.month, inicio.day + 1);
    return (await _motor()).consultar(lat: lat, lon: lon, desde: inicio, hasta: fin, radioKm: radioPorDefectoKm);
  }

  @override
  String get descripcionDatos {
    final e = _engine;
    if (e == null) return 'Datos oficiales incluidos en la app';
    final hasta = e.ultimoTurno?.toLocal();
    final fmt = hasta == null ? '' : ' (turnos publicados hasta ${hasta.day}/${hasta.month}/${hasta.year})';
    return 'Datos oficiales de ${e.generado.day}/${e.generado.month}/${e.generado.year}$fmt';
  }
}

class ApiRepository implements GuardiasRepository {
  final String base;
  final http.Client _cliente;

  ApiRepository(this.base, [http.Client? cliente]) : _cliente = cliente ?? http.Client();

  Future<Map<String, dynamic>> _get(String ruta, Map<String, String> q) async {
    final uri = Uri.parse(base).replace(path: ruta, queryParameters: q);
    final r = await _cliente.get(uri).timeout(const Duration(seconds: 15));
    if (r.statusCode != 200) throw Exception('Error ${r.statusCode} del servidor');
    return jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>;
  }

  ResultadoGuardias _convertir(Map<String, dynamic> j) {
    final guardias = (j['guardias'] as List? ?? []).map((g) {
      final f = g['farmacia'] as Map<String, dynamic>;
      final t = g['turno'] as Map<String, dynamic>;
      final fu = g['fuente'] as Map<String, dynamic>?;
      return Guardia(
        farmacia: Farmacia(
          id: f['id'] as String,
          titular: f['titular'] as String,
          direccion: f['direccion'] as String,
          localidad: f['localidad'] as String?,
          telefono: f['telefono'] as String?,
          telefonoGuardia: f['telefono_guardia'] as String?,
          lat: (f['lat'] as num?)?.toDouble(),
          lon: (f['lon'] as num?)?.toDouble(),
          precision: f['geo_precision'] as String?,
          fuente: fu == null
              ? null
              : Fuente(id: '', editor: fu['publisher'] as String, url: fu['url'] as String, licencia: fu['license'] as String),
        ),
        turno: Turno(
          tipo: tipoTurnoDesdeCodigo(t['tipo'] as String),
          inicio: DateTime.parse(t['inicio'] as String).toUtc(),
          fin: DateTime.parse(t['fin'] as String).toUtc(),
          zona: t['zona'] as String,
          horarioConfirmado: t['horario_confirmado'] as bool? ?? true,
        ),
        distanciaKm: (g['distancia_km'] as num).toDouble(),
      );
    }).toList();
    return ResultadoGuardias(
      cobertura: j['cobertura'] as bool? ?? false,
      mensaje: j['mensaje'] as String?,
      guardias: guardias,
    );
  }

  @override
  Future<ResultadoGuardias> ahora(double lat, double lon, DateTime instante) async => _convertir(await _get(
      '/v1/guardias', {'lat': '$lat', 'lon': '$lon', 'at': instante.toUtc().toIso8601String(), 'radius_km': '$radioPorDefectoKm'}));

  @override
  Future<ResultadoGuardias> dia(double lat, double lon, DateTime dia) async {
    final f = '${dia.year.toString().padLeft(4, '0')}-${dia.month.toString().padLeft(2, '0')}-${dia.day.toString().padLeft(2, '0')}';
    return _convertir(await _get('/v1/guardias/dia', {'lat': '$lat', 'lon': '$lon', 'fecha': f, 'radius_km': '$radioPorDefectoKm'}));
  }

  @override
  String get descripcionDatos => 'Datos oficiales en línea';
}

/// Acceso a los datos: instantánea local (por defecto) o API del backend.
///
/// Si la app se compila con `--dart-define=API_BASE=https://...` usa la API;
/// si no, la instantánea `assets/snapshot.json` incluida en la app.
library;

import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:http/http.dart' as http;

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

  SnapshotRepository([GuardiasEngine? engine]) : _engine = engine;

  Future<GuardiasEngine> _motor() {
    if (_engine != null) return Future.value(_engine!);
    return _cargando ??= () async {
      final texto = await rootBundle.loadString('assets/snapshot.json');
      final motor = await compute(_decodificar, texto);
      _engine = motor;
      return motor;
    }();
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

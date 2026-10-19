/// Cálculo de guardias sobre la instantánea local (sin servidor).
///
/// Reproduce las reglas de la API (/v1/guardias y /v1/guardias/dia):
/// - "Sin datos oficiales para esta zona" si no hay farmacias con turnos en el radio.
/// - "Sin datos oficiales para esta fecha" si las hay pero ninguna con turno.
/// - Solo se publican turnos que la fuente asigna explícitamente (no se extrapola).
library;

import 'dart:math' as math;

import '../models.dart';

const double radioTierraKm = 6371.0;

double distanciaKm(double lat1, double lon1, double lat2, double lon2) {
  final p1 = lat1 * math.pi / 180, p2 = lat2 * math.pi / 180;
  final dp = (lat2 - lat1) * math.pi / 180, dl = (lon2 - lon1) * math.pi / 180;
  final a = math.pow(math.sin(dp / 2), 2) + math.cos(p1) * math.cos(p2) * math.pow(math.sin(dl / 2), 2);
  return radioTierraKm * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a));
}

class TurnoIndexado {
  final int farmacia;
  final int zona;
  final int inicioMin;
  final int finMin;
  final TipoTurno tipo;
  final bool exacto;

  const TurnoIndexado(this.farmacia, this.zona, this.inicioMin, this.finMin, this.tipo, this.exacto);
}

class GuardiasEngine {
  final List<Farmacia> farmacias;
  final List<String> zonas;
  final List<TurnoIndexado> turnos; // ordenados por inicio
  final DateTime generado;
  late final Map<int, List<int>> _turnosPorFarmacia;
  late final Map<int, Set<int>> _zonasPorFarmacia;

  GuardiasEngine({required this.farmacias, required this.zonas, required this.turnos, required this.generado}) {
    _turnosPorFarmacia = {};
    _zonasPorFarmacia = {};
    for (var i = 0; i < turnos.length; i++) {
      final t = turnos[i];
      (_turnosPorFarmacia[t.farmacia] ??= []).add(i);
      (_zonasPorFarmacia[t.farmacia] ??= {}).add(t.zona);
    }
  }

  /// Fecha del último turno publicado (para avisar de datos caducados).
  DateTime? get ultimoTurno => turnos.isEmpty
      ? null
      : DateTime.fromMillisecondsSinceEpoch(turnos.map((t) => t.finMin).reduce(math.max) * 60000, isUtc: true);

  Map<int, double> _cercanas(double lat, double lon, double radioKm) {
    final out = <int, double>{};
    for (var i = 0; i < farmacias.length; i++) {
      final f = farmacias[i];
      if (!f.tieneCoordenadas || !_turnosPorFarmacia.containsKey(i)) continue;
      // Prefiltro barato por caja antes de la distancia exacta.
      if ((f.lat! - lat).abs() > radioKm / 110.0) continue;
      final d = distanciaKm(lat, lon, f.lat!, f.lon!);
      if (d <= radioKm) out[i] = d;
    }
    return out;
  }

  Turno _turno(TurnoIndexado t) => Turno(
        tipo: t.tipo,
        inicio: DateTime.fromMillisecondsSinceEpoch(t.inicioMin * 60000, isUtc: true),
        fin: DateTime.fromMillisecondsSinceEpoch(t.finMin * 60000, isUtc: true),
        zona: zonas[t.zona],
        horarioConfirmado: t.exacto,
      );

  /// Guardias cuyo turno se solapa con [desde, hasta). Si desde == hasta, activas en ese instante.
  ResultadoGuardias consultar({
    required double lat,
    required double lon,
    required DateTime desde,
    DateTime? hasta,
    double radioKm = 25,
    String mensajeSinFecha = 'Sin datos oficiales para esta fecha',
  }) {
    final cercanas = _cercanas(lat, lon, radioKm);
    if (cercanas.isEmpty) {
      return const ResultadoGuardias(
        cobertura: false,
        mensaje: 'Sin datos oficiales para esta zona',
        guardias: [],
      );
    }
    final ini = desde.toUtc().millisecondsSinceEpoch ~/ 60000;
    final fin = (hasta ?? desde).toUtc().millisecondsSinceEpoch ~/ 60000;
    bool solapa(TurnoIndexado t) => fin == ini ? (t.inicioMin <= ini && ini < t.finMin) : (t.inicioMin < fin && t.finMin > ini);

    final guardias = <Guardia>[];
    final vistos = <String>{};
    final zonasCercanas = <int>{};
    cercanas.forEach((idx, d) {
      zonasCercanas.addAll(_zonasPorFarmacia[idx] ?? const {});
      for (final ti in _turnosPorFarmacia[idx]!) {
        final t = turnos[ti];
        if (!solapa(t)) continue;
        // Una farmacia citada en varios cuadrantes a la misma hora se muestra una vez.
        final clave = '$idx|${t.inicioMin}|${t.finMin}';
        if (!vistos.add(clave)) continue;
        guardias.add(Guardia(farmacia: farmacias[idx], turno: _turno(t), distanciaKm: d));
      }
    });

    final sinCoordenadas = <Farmacia>[];
    for (var i = 0; i < farmacias.length; i++) {
      if (farmacias[i].tieneCoordenadas) continue;
      final ts = _turnosPorFarmacia[i];
      if (ts == null) continue;
      if (ts.any((ti) => solapa(turnos[ti]) && zonasCercanas.contains(turnos[ti].zona))) {
        sinCoordenadas.add(farmacias[i]);
      }
    }

    if (fin == ini) {
      guardias.sort((a, b) => a.distanciaKm.compareTo(b.distanciaKm));
    } else {
      guardias.sort((a, b) {
        final c = a.turno.inicio.compareTo(b.turno.inicio);
        return c != 0 ? c : a.distanciaKm.compareTo(b.distanciaKm);
      });
    }
    return ResultadoGuardias(
      cobertura: true,
      mensaje: guardias.isEmpty ? mensajeSinFecha : null,
      guardias: guardias,
      sinCoordenadas: sinCoordenadas,
    );
  }

  /// Construye el motor desde el JSON de scripts/export_snapshot.py.
  factory GuardiasEngine.desdeJson(Map<String, dynamic> json) {
    final fuentes = (json['sources'] as List)
        .map((s) => Fuente(id: s[0] as String, editor: s[1] as String, url: s[2] as String, licencia: s[3] as String))
        .toList();
    double? n(Object? v) => v == null ? null : (v as num).toDouble();
    final farmacias = (json['pharmacies'] as List)
        .map((p) => Farmacia(
              id: p[0] as String,
              titular: p[1] as String,
              direccion: p[2] as String,
              localidad: p[3] as String?,
              telefono: p[4] as String?,
              telefonoGuardia: p[5] as String?,
              lat: n(p[6]),
              lon: n(p[7]),
              precision: p[8] as String?,
              fuente: fuentes[p[9] as int],
            ))
        .toList();
    final turnos = (json['shifts'] as List)
        .map((t) => TurnoIndexado(t[0] as int, t[1] as int, t[2] as int, t[3] as int,
            tipoTurnoDesdeCodigo(t[4] as String), (t[5] as int) == 1))
        .toList();
    return GuardiasEngine(
      farmacias: farmacias,
      zonas: (json['zones'] as List).cast<String>(),
      turnos: turnos,
      generado: DateTime.parse(json['generated_at'] as String),
    );
  }
}

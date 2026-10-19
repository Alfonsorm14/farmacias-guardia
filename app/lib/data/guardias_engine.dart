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

  /// Periodo publicado por cada fuente: (primer inicio, último fin) en minutos UTC.
  late final Map<String, (int, int)> _periodoPorFuente;

  /// Caja (latMin, lonMin, latMax, lonMax) de las fuentes de un solo municipio.
  late final Map<String, (double, double, double, double)> _ambitoMunicipal;

  static const double _margenMunicipalKm = 2.0;

  GuardiasEngine({required this.farmacias, required this.zonas, required this.turnos, required this.generado}) {
    _turnosPorFarmacia = {};
    _zonasPorFarmacia = {};
    _periodoPorFuente = {};
    for (var i = 0; i < turnos.length; i++) {
      final t = turnos[i];
      (_turnosPorFarmacia[t.farmacia] ??= []).add(i);
      (_zonasPorFarmacia[t.farmacia] ??= {}).add(t.zona);
      final fid = farmacias[t.farmacia].fuente?.id ?? '';
      final p = _periodoPorFuente[fid];
      _periodoPorFuente[fid] = p == null ? (t.inicioMin, t.finMin) : (math.min(p.$1, t.inicioMin), math.max(p.$2, t.finMin));
    }
    _ambitoMunicipal = {};
    for (final f in farmacias) {
      final fu = f.fuente;
      if (fu == null || !fu.municipal || !f.tieneCoordenadas) continue;
      final a = _ambitoMunicipal[fu.id];
      _ambitoMunicipal[fu.id] = a == null
          ? (f.lat!, f.lon!, f.lat!, f.lon!)
          : (math.min(a.$1, f.lat!), math.min(a.$2, f.lon!), math.max(a.$3, f.lat!), math.max(a.$4, f.lon!));
    }
  }

  /// ¿El punto está dentro del ámbito de la fuente? (siempre, si no es municipal)
  bool _dentroDeAmbito(Fuente? fuente, double lat, double lon) {
    if (fuente == null || !fuente.municipal) return true;
    final a = _ambitoMunicipal[fuente.id];
    if (a == null) return false;
    final dLat = _margenMunicipalKm / 111.0;
    final dLon = _margenMunicipalKm / (111.0 * math.cos(lat * math.pi / 180));
    return lat >= a.$1 - dLat && lat <= a.$3 + dLat && lon >= a.$2 - dLon && lon <= a.$4 + dLon;
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
      // Las fuentes de un solo municipio no valen fuera de él (Alcalá no es Madrid).
      if (!_dentroDeAmbito(f.fuente, lat, lon)) continue;
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
    String mensajeSinPublicar = 'Aún no hay turnos oficiales publicados para esta fecha',
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

    // Periodo publicado por las fuentes de la zona: distingue "no hay guardia
    // asignada" de "aún no tenemos los turnos de esa fecha".
    final fuentesZona = {for (final idx in cercanas.keys) farmacias[idx].fuente?.id ?? ''};
    int? publicadoHasta;
    var fechaCubierta = false;
    for (final fid in fuentesZona) {
      final p = _periodoPorFuente[fid];
      if (p == null) continue;
      publicadoHasta = publicadoHasta == null ? p.$2 : math.max(publicadoHasta, p.$2);
      if (p.$1 <= math.max(ini, fin - 1) && ini < p.$2) fechaCubierta = true;
    }
    final datosHasta =
        publicadoHasta == null ? null : DateTime.fromMillisecondsSinceEpoch(publicadoHasta * 60000, isUtc: true);

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
      mensaje: guardias.isEmpty ? (fechaCubierta ? mensajeSinFecha : mensajeSinPublicar) : null,
      guardias: guardias,
      sinCoordenadas: sinCoordenadas,
      datosHasta: datosHasta,
    );
  }

  /// Construye el motor desde el JSON de scripts/export_snapshot.py.
  factory GuardiasEngine.desdeJson(Map<String, dynamic> json) {
    final fuentes = (json['sources'] as List)
        .map((s) => Fuente(
              id: s[0] as String,
              editor: s[1] as String,
              url: s[2] as String,
              licencia: s[3] as String,
              municipal: s.length > 5 && s[5] == true,
            ))
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

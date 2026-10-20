/// Cálculo de guardias sobre la instantánea local (sin servidor).
///
/// Reproduce las reglas de la API (/v1/guardias y /v1/guardias/dia):
/// - "Sin datos oficiales para esta zona" si no hay farmacias con turnos en el radio.
/// - "Sin datos oficiales para esta fecha" si las hay pero ninguna con turno.
/// - Solo se publican turnos que la fuente asigna explícitamente (no se extrapola).
library;

import 'dart:math' as math;

import '../models.dart';
import '../tiempo.dart';

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
  final List<Fuente> fuentes;
  final List<Farmacia> farmacias;
  final List<String> zonas;
  final List<TurnoIndexado> turnos; // ordenados por inicio
  final DateTime generado;
  late final Map<int, List<int>> _turnosPorFarmacia;
  late final Map<int, Set<int>> _zonasPorFarmacia;

  /// Periodo publicado por cada fuente: (primer inicio, último fin) en minutos UTC.
  /// (primer inicio, último fin, último inicio) de cada fuente, en minutos UTC.
  late final Map<String, (int, int, int)> _periodoPorFuente;

  /// Periodo publicado por cada zona (cuadrante): (primer inicio, último inicio, último fin), minutos UTC.
  late final Map<int, (int, int, int)> _periodoPorZona;

  /// Inicios de los turnos de cada zona, ordenados (minutos UTC).
  late final Map<int, List<int>> _iniciosPorZona;

  /// Caja (latMin, lonMin, latMax, lonMax) de las fuentes de un solo municipio: solo respaldo si la
  /// instantánea no trae el polígono del término municipal.
  late final Map<String, (double, double, double, double)> _ambitoMunicipal;

  static const double _margenMunicipalKm = 2.0;

  /// Una zona con turnos a menos de 7 días de la fecha se considera publicada (cuadrantes de fines
  /// de semana o semanales). Igual que ZONE_GAP en backend/api.py.
  static const int _huecoZonaMin = 7 * 24 * 60;

  GuardiasEngine({
    required this.farmacias,
    required this.zonas,
    required this.turnos,
    required this.generado,
    List<Fuente>? fuentes,
  }) : fuentes = fuentes ?? {for (final f in farmacias) if (f.fuente != null) f.fuente!.id: f.fuente!}.values.toList() {
    _turnosPorFarmacia = {};
    _zonasPorFarmacia = {};
    _periodoPorFuente = {};
    _periodoPorZona = {};
    _iniciosPorZona = {};
    for (var i = 0; i < turnos.length; i++) {
      final t = turnos[i];
      final pz = _periodoPorZona[t.zona];
      _periodoPorZona[t.zona] = pz == null
          ? (t.inicioMin, t.inicioMin, t.finMin)
          : (math.min(pz.$1, t.inicioMin), math.max(pz.$2, t.inicioMin), math.max(pz.$3, t.finMin));
      (_iniciosPorZona[t.zona] ??= []).add(t.inicioMin);
      (_turnosPorFarmacia[t.farmacia] ??= []).add(i);
      (_zonasPorFarmacia[t.farmacia] ??= {}).add(t.zona);
      final fid = farmacias[t.farmacia].fuente?.id ?? '';
      final p = _periodoPorFuente[fid];
      _periodoPorFuente[fid] = p == null
          ? (t.inicioMin, t.finMin, t.inicioMin)
          : (math.min(p.$1, t.inicioMin), math.max(p.$2, t.finMin), math.max(p.$3, t.inicioMin));
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
    for (final l in _iniciosPorZona.values) {
      l.sort();
    }
  }

  /// ¿Algún turno de la zona empieza en [desde, hasta)?
  bool _hayInicioEntre(int zona, int desde, int hasta) {
    final l = _iniciosPorZona[zona];
    if (l == null || l.isEmpty) return false;
    var lo = 0, hi = l.length;
    while (lo < hi) {
      final mid = (lo + hi) >> 1;
      if (l[mid] < desde) {
        lo = mid + 1;
      } else {
        hi = mid;
      }
    }
    return lo < l.length && l[lo] < hasta;
  }

  /// Punto en polígono (par/impar) sobre un anillo de [lat, lon].
  static bool _enAnillo(List<List<double>> anillo, double lat, double lon) {
    var dentro = false;
    for (var i = 0, j = anillo.length - 1; i < anillo.length; j = i++) {
      final yi = anillo[i][0], xi = anillo[i][1], yj = anillo[j][0], xj = anillo[j][1];
      if ((yi > lat) != (yj > lat) && lon < xi + (lat - yi) * (xj - xi) / (yj - yi)) dentro = !dentro;
    }
    return dentro;
  }

  /// ¿El punto está dentro del ámbito de la fuente? (siempre, si no es municipal)
  bool _dentroDeAmbito(Fuente? fuente, double lat, double lon) {
    if (fuente == null || !fuente.municipal) return true;
    final termino = fuente.termino;
    if (termino != null && termino.isNotEmpty) {
      // Término municipal (OpenStreetMap): fijo, no depende de las farmacias de guardia del día.
      return termino.any((pol) =>
          pol.isNotEmpty && _enAnillo(pol.first, lat, lon) && !pol.skip(1).any((h) => _enAnillo(h, lat, lon)));
    }
    final a = _ambitoMunicipal[fuente.id];
    if (a == null) return false;
    final dLat = _margenMunicipalKm / 111.0;
    final dLon = _margenMunicipalKm / (111.0 * math.cos(lat * math.pi / 180));
    return lat >= a.$1 - dLat && lat <= a.$3 + dLat && lon >= a.$2 - dLon && lon <= a.$4 + dLon;
  }

  /// Inicio del último turno publicado (el día hasta el que hay turnos).
  DateTime? get ultimoInicio => turnos.isEmpty
      ? null
      : DateTime.fromMillisecondsSinceEpoch(turnos.map((t) => t.inicioMin).reduce(math.max) * 60000, isUtc: true);

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

  /// Preferencia del cuadrante de un turno para su farmacia (menor es mejor): el de su localidad,
  /// luego el que la contiene y, a igualdad, el de nombre más corto. Igual que
  /// select_best_shift_for_pharmacy en backend/api.py.
  int _puntuacion(int farmacia, TurnoIndexado t) {
    final loc = (farmacias[farmacia].localidad ?? '').trim().toUpperCase();
    final zona = zonas[t.zona].trim().toUpperCase();
    final coincide = loc.isNotEmpty && zona == loc
        ? 0
        : loc.isNotEmpty && zona.contains(loc)
            ? 1
            : 3;
    return coincide * 100000 + zonas[t.zona].length;
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
    String mensajeAnterior = 'No tenemos los turnos oficiales de esa fecha',
    String mensajeZonaSinPublicar = 'Sin turnos oficiales publicados para tu zona en esta fecha',
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
    final zonasCercanas = <int>{};
    final instante = fin == ini;
    cercanas.forEach((idx, d) {
      zonasCercanas.addAll(_zonasPorFarmacia[idx] ?? const {});
      // Una farmacia citada en varios cuadrantes se muestra una vez (como la API): en "Ahora", un
      // turno por farmacia; en un día, uno por (tipo, inicio). Se elige el cuadrante de su localidad.
      final grupos = <String, TurnoIndexado>{};
      for (final ti in _turnosPorFarmacia[idx]!) {
        final t = turnos[ti];
        if (!solapa(t)) continue;
        final clave = instante ? '' : '${t.tipo.index}|${t.inicioMin}';
        final previo = grupos[clave];
        if (previo == null || _puntuacion(idx, t) < _puntuacion(idx, previo)) grupos[clave] = t;
      }
      for (final t in grupos.values) {
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
    var antesDeLosDatos = true; // la fecha es anterior al primer turno de todas las fuentes
    final sonda = math.max(ini, fin - 1);
    for (final fid in fuentesZona) {
      final p = _periodoPorFuente[fid];
      if (p == null) continue;
      // "Publicados hasta": inicio del último turno (una nocturna del 31/12 acaba el 1/1).
      publicadoHasta = publicadoHasta == null ? p.$3 : math.max(publicadoHasta, p.$3);
      if (p.$1 <= sonda && ini < p.$2) fechaCubierta = true;
      if (sonda >= p.$1) antesDeLosDatos = false;
    }
    final datosHasta =
        publicadoHasta == null ? null : DateTime.fromMillisecondsSinceEpoch(publicadoHasta * 60000, isUtc: true);

    // ¿La zona de la farmacia más cercana tiene turnos publicados para la fecha? Si no (p. ej.
    // agrupaciones de Murcia con solo enero publicado), lo que se muestra es de zonas vecinas.
    String? aviso;
    if (fechaCubierta) {
      final masCercana = cercanas.entries.reduce((a, b) => a.value <= b.value ? a : b).key;
      final propias = _zonasPorFarmacia[masCercana] ?? const <int>{};
      // Publicada = dentro del periodo de la zona y con turnos a menos de 7 días (Yecla publica
      // enero y agosto: marzo no está publicado aunque caiga entre los dos).
      final cubiertas = propias.any((z) {
        final p = _periodoPorZona[z];
        return p != null &&
            p.$1 <= sonda &&
            ini < p.$3 &&
            _hayInicioEntre(z, ini - _huecoZonaMin, fin + _huecoZonaMin);
      });
      if (propias.isNotEmpty && !cubiertas) {
        final nombres = (propias.map((z) => zonas[z]).toList()..sort()).join(', ');
        final ultimoFin = propias.map((z) => _periodoPorZona[z]?.$3 ?? 0).reduce(math.max);
        final ultimoInicio = propias.map((z) => _periodoPorZona[z]?.$2 ?? 0).reduce(math.max);
        aviso = ini >= ultimoFin
            ? 'La fuente oficial solo ha publicado los turnos de tu zona ($nombres) hasta el ${_fecha(ultimoInicio)}.'
            : 'La fuente oficial no ha publicado los turnos de tu zona ($nombres) para esta fecha.';
        aviso += guardias.isEmpty ? ' No hay guardias de zonas cercanas.' : ' Se muestran guardias de zonas cercanas.';
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
      mensaje: guardias.isNotEmpty
          ? null
          : aviso != null
              ? mensajeZonaSinPublicar
              : fechaCubierta
                  ? mensajeSinFecha
                  : (antesDeLosDatos ? mensajeAnterior : mensajeSinPublicar),
      guardias: guardias,
      sinCoordenadas: sinCoordenadas,
      datosHasta: datosHasta,
      aviso: aviso,
    );
  }

  /// Día/mes/año (hora de Madrid) del instante [min] (minutos UTC).
  static String _fecha(int min) {
    final d = enMadrid(DateTime.fromMillisecondsSinceEpoch(min * 60000, isUtc: true));
    return '${d.day}/${d.month}/${d.year}';
  }

  /// Las fechas de la base de datos se guardan en UTC sin zona ("2026-10-19 17:23:35.190233").
  static DateTime? _fechaUtc(String texto) =>
      DateTime.tryParse(RegExp(r'(Z|[+-]\d\d:?\d\d)$').hasMatch(texto) ? texto : '${texto}Z')?.toUtc();

  /// Construye el motor desde el JSON de scripts/export_snapshot.py.
  factory GuardiasEngine.desdeJson(Map<String, dynamic> json) {
    final fuentes = (json['sources'] as List)
        .map((s) => Fuente(
              id: s[0] as String,
              editor: s[1] as String,
              url: s[2] as String,
              licencia: s[3] as String,
              municipal: s.length > 5 && s[5] == true,
              termino: s.length > 6 && s[6] is List
                  ? [
                      for (final pol in s[6] as List)
                        [
                          for (final anillo in pol as List)
                            [for (final pt in anillo as List) [((pt as List)[0] as num).toDouble(), (pt[1] as num).toDouble()]]
                        ]
                    ]
                  : null,
              descargado: s.length > 4 && s[4] is String ? _fechaUtc(s[4] as String) : null,
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
      fuentes: fuentes,
      farmacias: farmacias,
      zonas: (json['zones'] as List).cast<String>(),
      turnos: turnos,
      generado: DateTime.parse(json['generated_at'] as String),
    );
  }
}

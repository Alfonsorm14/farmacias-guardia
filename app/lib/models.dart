/// Modelos de datos de la app de farmacias de guardia.
library;

enum TipoTurno { diurna, nocturna, veinticuatroHoras, localizada, refuerzo }

TipoTurno tipoTurnoDesdeCodigo(String codigo) {
  switch (codigo) {
    case 'd':
    case 'diurna':
      return TipoTurno.diurna;
    case 'n':
    case 'nocturna':
      return TipoTurno.nocturna;
    case 'c':
    case '24h':
      return TipoTurno.veinticuatroHoras;
    case 'l':
    case 'localizada':
      return TipoTurno.localizada;
    default:
      return TipoTurno.refuerzo;
  }
}

String etiquetaTipo(TipoTurno tipo) {
  switch (tipo) {
    case TipoTurno.diurna:
      return 'Diurna';
    case TipoTurno.nocturna:
      return 'Nocturna';
    case TipoTurno.veinticuatroHoras:
      return '24 horas';
    case TipoTurno.localizada:
      return 'Localizada';
    case TipoTurno.refuerzo:
      return 'Refuerzo';
  }
}

class Fuente {
  final String id;
  final String editor;
  final String url;
  final String licencia;

  /// La fuente solo cubre un término municipal (Madrid, Zaragoza).
  final bool municipal;

  /// Fecha de la última descarga de la fuente (UTC), si se conoce.
  final DateTime? descargado;

  /// Término municipal de una fuente municipal: polígonos [anillo exterior, huecos...] de [lat, lon].
  final List<List<List<List<double>>>>? termino;

  const Fuente({
    required this.id,
    required this.editor,
    required this.url,
    required this.licencia,
    this.municipal = false,
    this.descargado,
    this.termino,
  });
}

class Farmacia {
  final String id;
  final String titular;
  final String direccion;
  final String? localidad;
  final String? telefono;
  final String? telefonoGuardia;
  final double? lat;
  final double? lon;
  final String? precision;
  final Fuente? fuente;

  const Farmacia({
    required this.id,
    required this.titular,
    required this.direccion,
    this.localidad,
    this.telefono,
    this.telefonoGuardia,
    this.lat,
    this.lon,
    this.precision,
    this.fuente,
  });

  bool get tieneCoordenadas => lat != null && lon != null;

  /// La ubicación es el centro del núcleo de población, no el portal.
  bool get ubicacionAproximada => precision == 'localidad';

  /// Teléfono al que llamar durante la guardia (el específico si existe).
  String? get telefonoParaLlamar => telefonoGuardia ?? telefono;
}

class Turno {
  final TipoTurno tipo;
  final DateTime inicio; // UTC
  final DateTime fin; // UTC
  final String zona;
  final bool horarioConfirmado;

  const Turno({
    required this.tipo,
    required this.inicio,
    required this.fin,
    required this.zona,
    required this.horarioConfirmado,
  });

  bool activoEn(DateTime instante) => !instante.isBefore(inicio) && instante.isBefore(fin);
}

class Guardia {
  final Farmacia farmacia;
  final Turno turno;
  final double distanciaKm;

  const Guardia({required this.farmacia, required this.turno, required this.distanciaKm});
}

/// Resultado de una consulta: cobertura, mensaje y guardias ordenadas.
class ResultadoGuardias {
  /// false = la zona no tiene datos oficiales (comunidad no cubierta aún).
  final bool cobertura;

  /// Mensaje para el usuario cuando no hay guardias que mostrar.
  final String? mensaje;
  final List<Guardia> guardias;

  /// Farmacias de guardia en la zona que no se han podido situar en el mapa.
  final List<Farmacia> sinCoordenadas;

  /// Inicio del último turno publicado por las fuentes de la zona (el día hasta el que hay turnos).
  final DateTime? datosHasta;

  /// Aviso cuando la zona de las farmacias más cercanas no tiene turnos publicados para la
  /// fecha y lo que se muestra son guardias de zonas vecinas.
  final String? aviso;

  const ResultadoGuardias({
    required this.cobertura,
    required this.guardias,
    this.mensaje,
    this.sinCoordenadas = const [],
    this.datosHasta,
    this.aviso,
  });
}

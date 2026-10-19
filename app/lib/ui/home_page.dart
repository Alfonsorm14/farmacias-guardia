import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../data/preferencias.dart';
import '../data/repository.dart';
import '../location.dart';
import '../models.dart';
import '../tiempo.dart';
import 'acerca_de.dart';
import 'elegir_lugar.dart';
import 'guardia_card.dart';
import 'mapa.dart';

enum Vista { ahora, hoy, manana, pasado, fecha }

class HomePage extends StatefulWidget {
  final GuardiasRepository repositorio;

  /// Ubicación inicial (tests); si es null se intenta el GPS.
  final Ubicacion? ubicacionInicial;

  /// Reloj inyectable para tests (por defecto, la hora actual).
  final DateTime Function()? reloj;

  const HomePage({super.key, required this.repositorio, this.ubicacionInicial, this.reloj});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> with WidgetsBindingObserver {
  Ubicacion? _ubicacion;
  String? _errorUbicacion;
  bool _buscandoGps = false;
  Vista _vista = Vista.ahora;
  DateTime? _fechaElegida; // día de Madrid elegido en el calendario (Vista.fecha)
  bool _verMapa = false;
  Future<ResultadoGuardias>? _consulta;

  DateTime _ahora() => (widget.reloj ?? DateTime.now)();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    if (widget.ubicacionInicial != null) {
      _fijarUbicacion(widget.ubicacionInicial!);
    } else {
      _usarGps();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Al volver a la app horas después, "Ahora" debe recalcularse.
    if (state == AppLifecycleState.resumed && _ubicacion != null) {
      setState(_consultar);
    }
  }

  Future<void> _usarGps() async {
    setState(() {
      _buscandoGps = true;
      _errorUbicacion = null;
    });
    try {
      final u = await ubicacionGps();
      if (!mounted) return;
      _fijarUbicacion(u);
    } catch (e) {
      if (!mounted) return;
      final error = e is ErrorUbicacion ? e.mensaje : 'No se pudo obtener la ubicación.';
      // Sin GPS, se vuelve al último lugar elegido a mano (si lo hay).
      final ultimo = _ubicacion == null ? await leerUltimoLugar() : null;
      if (!mounted) return;
      if (ultimo != null) {
        _fijarUbicacion(ultimo);
        ScaffoldMessenger.maybeOf(context)?.showSnackBar(SnackBar(content: Text('$error Se muestra ${ultimo.etiqueta}.')));
      } else {
        setState(() => _errorUbicacion = error);
      }
    } finally {
      if (mounted) setState(() => _buscandoGps = false);
    }
  }

  void _fijarUbicacion(Ubicacion u) {
    guardarUltimoLugar(u);
    setState(() {
      _ubicacion = u;
      _errorUbicacion = null;
      _consultar();
    });
  }

  void _consultar() {
    final u = _ubicacion;
    if (u == null) return;
    final ahora = _ahora();
    // "Hoy" es el día natural de España peninsular, aunque el teléfono esté en otra zona.
    final m = enMadrid(ahora);
    final hoy = DateTime(m.year, m.month, m.day);
    _consulta = switch (_vista) {
      Vista.ahora => widget.repositorio.ahora(u.lat, u.lon, ahora),
      Vista.hoy => widget.repositorio.dia(u.lat, u.lon, hoy),
      Vista.manana => widget.repositorio.dia(u.lat, u.lon, DateTime(hoy.year, hoy.month, hoy.day + 1)),
      Vista.pasado => widget.repositorio.dia(u.lat, u.lon, DateTime(hoy.year, hoy.month, hoy.day + 2)),
      Vista.fecha => widget.repositorio.dia(u.lat, u.lon, _fechaElegida ?? hoy),
    };
  }

  Future<void> _elegirFecha() async {
    final m = enMadrid(_ahora());
    final hoy = DateTime(m.year, m.month, m.day);
    final f = await showDatePicker(
      context: context,
      // Si la app lleva días abierta, la fecha elegida puede haber quedado antes del primer día.
      initialDate: (_fechaElegida == null || _fechaElegida!.isBefore(DateTime(hoy.year, hoy.month, hoy.day - 31)))
          ? hoy
          : _fechaElegida!,
      firstDate: DateTime(hoy.year, hoy.month, hoy.day - 31),
      lastDate: DateTime(hoy.year + 1, 12, 31),
      helpText: 'Elegir fecha',
    );
    if (f == null || !mounted) return;
    setState(() {
      _fechaElegida = DateTime(f.year, f.month, f.day);
      _vista = Vista.fecha;
      _consultar();
    });
  }

  void _abrirAcercaDe() {
    Navigator.push(context, MaterialPageRoute(builder: (_) => AcercaDePage(repositorio: widget.repositorio)));
  }

  Future<void> _elegirLugar() async {
    final elegido = await Navigator.push<Ubicacion>(
      context,
      MaterialPageRoute(builder: (_) => const ElegirLugarPage()),
    );
    if (elegido == null || !mounted) return;
    if (identical(elegido, usarGps) || elegido.etiqueta == usarGps.etiqueta) {
      _usarGps();
    } else {
      _fijarUbicacion(elegido);
    }
  }

  @override
  Widget build(BuildContext context) {
    final u = _ubicacion;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Farmacias de guardia'),
        actions: [
          IconButton(
            tooltip: _verMapa ? 'Ver lista' : 'Ver mapa',
            icon: Icon(_verMapa ? Icons.list : Icons.map_outlined),
            onPressed: u == null ? null : () => setState(() => _verMapa = !_verMapa),
          ),
          IconButton(tooltip: 'Elegir fecha', icon: const Icon(Icons.calendar_month_outlined), onPressed: _elegirFecha),
          PopupMenuButton<String>(
            tooltip: 'Más opciones',
            onSelected: (v) => v == 'lugar' ? _elegirLugar() : _abrirAcercaDe(),
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'lugar', child: Text('Elegir lugar')),
              PopupMenuItem(value: 'acerca', child: Text('Fuentes y privacidad')),
            ],
          ),
        ],
      ),
      body: Column(
        children: [
          _barraUbicacion(u),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
            child: SegmentedButton<Vista>(
              showSelectedIcon: false,
              emptySelectionAllowed: true,
              segments: const [
                ButtonSegment(value: Vista.ahora, label: Text('Ahora')),
                ButtonSegment(value: Vista.hoy, label: Text('Hoy')),
                ButtonSegment(value: Vista.manana, label: Text('Mañana')),
                ButtonSegment(value: Vista.pasado, label: Text('Pasado')),
              ],
              selected: _vista == Vista.fecha ? const {} : {_vista},
              onSelectionChanged: (s) {
                if (s.isEmpty) return; // pulsar la pestaña activa no la deselecciona
                setState(() {
                  _vista = s.first;
                  _consultar();
                });
              },
            ),
          ),
          if (_vista == Vista.fecha && _fechaElegida != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: InputChip(
                avatar: const Icon(Icons.event, size: 18),
                label: Text(DateFormat("EEEE d 'de' MMMM 'de' y", 'es_ES').format(_fechaElegida!)),
                onPressed: _elegirFecha,
                deleteButtonTooltipMessage: 'Quitar fecha',
                onDeleted: () => setState(() {
                  _vista = Vista.ahora;
                  _fechaElegida = null;
                  _consultar();
                }),
              ),
            ),
          Expanded(child: u == null ? _sinUbicacion() : _resultados(u)),
        ],
      ),
    );
  }

  Widget _barraUbicacion(Ubicacion? u) {
    return Material(
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: ListTile(
        dense: true,
        leading: _buscandoGps
            ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
            : Icon(u?.esGps == true ? Icons.my_location : Icons.place),
        title: Text(_buscandoGps ? 'Buscando tu ubicación…' : (u?.etiqueta ?? 'Sin ubicación')),
        trailing: TextButton(onPressed: _elegirLugar, child: const Text('Cambiar')),
      ),
    );
  }

  Widget _sinUbicacion() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.location_off_outlined, size: 48),
            const SizedBox(height: 12),
            Text(_errorUbicacion ?? 'Necesito tu ubicación para buscar la farmacia de guardia más cercana.',
                textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton.icon(onPressed: _usarGps, icon: const Icon(Icons.my_location), label: const Text('Usar GPS')),
            TextButton(onPressed: _elegirLugar, child: const Text('Elegir un lugar')),
          ],
        ),
      ),
    );
  }

  Widget _resultados(Ubicacion u) {
    return FutureBuilder<ResultadoGuardias>(
      future: _consulta,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return _aviso(Icons.cloud_off, 'No se han podido cargar los datos', '${snap.error}');
        }
        final r = snap.data!;
        if (!r.cobertura) {
          return _aviso(Icons.travel_explore, r.mensaje ?? 'Sin datos oficiales para esta zona',
              'Por ahora la app tiene los turnos oficiales de Baleares, la Región de Murcia, Navarra y las ciudades de Madrid y Zaragoza. '
                  'Iremos añadiendo comunidades a medida que publiquen sus datos.');
        }
        if (_verMapa) {
          return MapaGuardias(
            ubicacion: u,
            guardias: r.guardias,
            aviso: r.aviso ?? (r.guardias.isEmpty ? (r.mensaje ?? 'Sin datos oficiales para esta fecha') : null),
          );
        }
        final fuentes = {
          for (final g in r.guardias)
            if (g.farmacia.fuente != null) '${g.farmacia.fuente!.editor} (${g.farmacia.fuente!.licencia})',
        };
        final pie = Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
          child: Text(
            '${widget.repositorio.descripcionDatos}.'
            '${r.datosHasta == null || r.aviso != null ? '' : ' Turnos oficiales de tu zona publicados hasta el ${_fechaCorta(r.datosHasta!)}.'}'
            '${fuentes.isEmpty ? '' : ' Fuente: ${fuentes.join('; ')}.'}'
            ' Antes de desplazarte, confirma la guardia por teléfono.',
            style: Theme.of(context).textTheme.bodySmall,
            textAlign: TextAlign.center,
          ),
        );
        final aviso = r.aviso == null
            ? null
            : Card(
                margin: const EdgeInsets.fromLTRB(12, 8, 12, 4),
                color: Theme.of(context).colorScheme.tertiaryContainer,
                child: ListTile(
                  leading: const Icon(Icons.info_outline),
                  title: Text(r.aviso!),
                  subtitle: const Text('Antes de desplazarte, llama a las farmacias de tu localidad.'),
                ),
              );
        if (r.guardias.isEmpty) {
          final mensaje = r.mensaje ?? 'Sin datos oficiales para esta fecha';
          final String detalle;
          if (r.aviso != null) {
            detalle = '${r.aviso!} Antes de desplazarte, llama a las farmacias de tu localidad.';
          } else if (mensaje.startsWith('Aún no')) {
            detalle = 'La fuente oficial todavía no ha publicado los turnos de esa fecha.';
          } else if (mensaje.startsWith('No tenemos')) {
            detalle = 'La app solo guarda los turnos publicados recientemente; los de esa fecha no están disponibles.';
          } else {
            detalle = 'La fuente oficial no asigna farmacia de guardia en tu zona para este momento.';
          }
          return ListView(children: [_aviso(Icons.event_busy, mensaje, detalle), pie]);
        }
        return ListView(
          children: [
            ?aviso,
            for (final g in r.guardias) GuardiaCard(guardia: g, ahora: _ahora()),
            if (r.sinCoordenadas.isNotEmpty)
              Card(
                margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                child: ExpansionTile(
                  leading: const Icon(Icons.not_listed_location_outlined),
                  title: Text('${r.sinCoordenadas.length} de guardia en tu zona sin situar en el mapa'),
                  children: [
                    for (final f in r.sinCoordenadas)
                      ListTile(title: Text(f.titular), subtitle: Text(f.direccion), trailing: f.telefonoParaLlamar == null ? null : Text(f.telefonoParaLlamar!)),
                  ],
                ),
              ),
            pie,
          ],
        );
      },
    );
  }

  String _fechaCorta(DateTime d) {
    final m = enMadrid(d.subtract(const Duration(minutes: 1)));
    return '${m.day}/${m.month}/${m.year}';
  }

  Widget _aviso(IconData icono, String titulo, String detalle) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icono, size: 48),
          const SizedBox(height: 12),
          Text(titulo, style: Theme.of(context).textTheme.titleMedium, textAlign: TextAlign.center),
          const SizedBox(height: 8),
          Text(detalle, textAlign: TextAlign.center),
        ],
      ),
    );
  }
}

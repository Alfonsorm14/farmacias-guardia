import 'package:flutter/material.dart';

import '../data/repository.dart';
import '../location.dart';
import '../models.dart';
import 'guardia_card.dart';
import 'mapa.dart';

enum Vista { ahora, hoy, manana, pasado }

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

class _HomePageState extends State<HomePage> {
  Ubicacion? _ubicacion;
  String? _errorUbicacion;
  bool _buscandoGps = false;
  Vista _vista = Vista.ahora;
  bool _verMapa = false;
  Future<ResultadoGuardias>? _consulta;

  DateTime _ahora() => (widget.reloj ?? DateTime.now)();

  @override
  void initState() {
    super.initState();
    if (widget.ubicacionInicial != null) {
      _fijarUbicacion(widget.ubicacionInicial!);
    } else {
      _usarGps();
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
      setState(() => _errorUbicacion = e is ErrorUbicacion ? e.mensaje : 'No se pudo obtener la ubicación.');
    } finally {
      if (mounted) setState(() => _buscandoGps = false);
    }
  }

  void _fijarUbicacion(Ubicacion u) {
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
    final hoy = DateTime(ahora.year, ahora.month, ahora.day);
    _consulta = switch (_vista) {
      Vista.ahora => widget.repositorio.ahora(u.lat, u.lon, ahora),
      Vista.hoy => widget.repositorio.dia(u.lat, u.lon, hoy),
      Vista.manana => widget.repositorio.dia(u.lat, u.lon, DateTime(hoy.year, hoy.month, hoy.day + 1)),
      Vista.pasado => widget.repositorio.dia(u.lat, u.lon, DateTime(hoy.year, hoy.month, hoy.day + 2)),
    };
  }

  Future<void> _elegirLugar() async {
    final elegido = await showModalBottomSheet<Ubicacion>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            ListTile(
              leading: const Icon(Icons.my_location),
              title: const Text('Usar mi ubicación (GPS)'),
              onTap: () => Navigator.pop(ctx, const Ubicacion(0, 0, '__gps__')),
            ),
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 8, 16, 4),
              child: Text('Zonas con datos oficiales cargados (Baleares, Región de Murcia, Navarra y ciudad de Madrid):'),
            ),
            for (final l in lugaresConDatos)
              ListTile(leading: const Icon(Icons.place_outlined), title: Text(l.etiqueta), onTap: () => Navigator.pop(ctx, l)),
          ],
        ),
      ),
    );
    if (elegido == null) return;
    if (elegido.etiqueta == '__gps__') {
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
          IconButton(tooltip: 'Elegir lugar', icon: const Icon(Icons.edit_location_alt_outlined), onPressed: _elegirLugar),
        ],
      ),
      body: Column(
        children: [
          _barraUbicacion(u),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
            child: SegmentedButton<Vista>(
              showSelectedIcon: false,
              segments: const [
                ButtonSegment(value: Vista.ahora, label: Text('Ahora')),
                ButtonSegment(value: Vista.hoy, label: Text('Hoy')),
                ButtonSegment(value: Vista.manana, label: Text('Mañana')),
                ButtonSegment(value: Vista.pasado, label: Text('Pasado')),
              ],
              selected: {_vista},
              onSelectionChanged: (s) => setState(() {
                _vista = s.first;
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
              'Por ahora la app tiene los turnos oficiales de Baleares, la Región de Murcia, Navarra y la ciudad de Madrid. '
                  'Iremos añadiendo comunidades a medida que publiquen sus datos.');
        }
        if (_verMapa) {
          return MapaGuardias(ubicacion: u, guardias: r.guardias);
        }
        final fuentes = {
          for (final g in r.guardias)
            if (g.farmacia.fuente != null) '${g.farmacia.fuente!.editor} (${g.farmacia.fuente!.licencia})',
        };
        final pie = Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
          child: Text(
            '${widget.repositorio.descripcionDatos}.'
            '${fuentes.isEmpty ? '' : ' Fuente: ${fuentes.join('; ')}.'}'
            ' Antes de desplazarte, confirma la guardia por teléfono.',
            style: Theme.of(context).textTheme.bodySmall,
            textAlign: TextAlign.center,
          ),
        );
        if (r.guardias.isEmpty) {
          return ListView(children: [
            _aviso(Icons.event_busy, r.mensaje ?? 'Sin datos oficiales para esta fecha',
                'La fuente oficial no asigna farmacia de guardia en tu zona para este momento.'),
            pie,
          ]);
        }
        return ListView(
          children: [
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

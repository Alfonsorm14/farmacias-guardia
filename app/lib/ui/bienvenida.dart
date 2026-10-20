import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../data/repository.dart';
import '../location.dart';
import '../models.dart';
import 'cobertura.dart';
import 'home_page.dart';

const _claveVista = 'bienvenida_vista_v1';

/// Primera pantalla: qué hace la app, dónde funciona y para qué se pide la ubicación (antes del
/// aviso de permisos del sistema). Solo se enseña la primera vez.
class BienvenidaPage extends StatefulWidget {
  final GuardiasRepository repositorio;
  final VoidCallback alTerminar;
  final DateTime Function()? reloj;

  const BienvenidaPage({super.key, required this.repositorio, required this.alTerminar, this.reloj});

  @override
  State<BienvenidaPage> createState() => _BienvenidaPageState();
}

class _BienvenidaPageState extends State<BienvenidaPage> {
  late final DateTime _ahora = (widget.reloj ?? DateTime.now)();
  late final Future<List<Cobertura>> _cobertura = widget.repositorio.cobertura(_ahora);

  @override
  Widget build(BuildContext context) {
    final estilos = Theme.of(context).textTheme;
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 24, 20, 24),
          children: [
            Icon(Icons.local_pharmacy, size: 56, color: Theme.of(context).colorScheme.primary),
            const SizedBox(height: 12),
            Text('Farmacia de guardia cerca', style: estilos.headlineSmall, textAlign: TextAlign.center),
            const SizedBox(height: 8),
            const Text(
              'Las farmacias de guardia más cercanas, ahora o el día que elijas, con los turnos oficiales que '
              'publican las administraciones. Si no hay turnos publicados para tu zona, la app te lo dice.',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 20),
            Text('Dónde funciona', style: estilos.titleMedium),
            FutureBuilder<List<Cobertura>>(
              future: _cobertura,
              builder: (context, snap) => snap.hasData
                  ? ListaCobertura(cobertura: snap.data!, ahora: _ahora)
                  : const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator())),
            ),
            const SizedBox(height: 12),
            Text('Tu ubicación', style: estilos.titleMedium),
            const SizedBox(height: 4),
            const Text(
              'Para buscar las farmacias más cercanas te pediremos permiso para usar tu ubicación mientras '
              'usas la app. Se usa en el teléfono y la app no la envía a ningún servidor propio. Si lo '
              'prefieres, puedes elegir un lugar a mano.',
            ),
            const SizedBox(height: 12),
            Text(
              'Esta app no es oficial ni está vinculada a las administraciones ni a los colegios de '
              'farmacéuticos. Antes de desplazarte, confirma la guardia por teléfono.',
              style: estilos.bodySmall,
            ),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: () async {
                try {
                  final p = await SharedPreferences.getInstance();
                  await p.setBool(_claveVista, true);
                } catch (_) {}
                widget.alTerminar();
              },
              child: const Text('Empezar'),
            ),
          ],
        ),
      ),
    );
  }
}

/// Raíz de la app: bienvenida la primera vez y después la pantalla principal.
class Inicio extends StatefulWidget {
  final GuardiasRepository repositorio;
  final Ubicacion? ubicacionInicial; // pruebas
  final DateTime Function()? reloj; // pruebas

  const Inicio({super.key, required this.repositorio, this.ubicacionInicial, this.reloj});

  @override
  State<Inicio> createState() => _InicioState();
}

class _InicioState extends State<Inicio> {
  bool? _vista;

  @override
  void initState() {
    super.initState();
    () async {
      var vista = false;
      try {
        vista = (await SharedPreferences.getInstance()).getBool(_claveVista) ?? false;
      } catch (_) {}
      if (mounted) setState(() => _vista = vista);
    }();
  }

  @override
  Widget build(BuildContext context) {
    final vista = _vista;
    if (vista == null) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    if (!vista) {
      return BienvenidaPage(
          repositorio: widget.repositorio, reloj: widget.reloj, alTerminar: () => setState(() => _vista = true));
    }
    return HomePage(repositorio: widget.repositorio, ubicacionInicial: widget.ubicacionInicial, reloj: widget.reloj);
  }
}

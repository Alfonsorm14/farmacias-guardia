import 'dart:async';

import 'package:flutter/material.dart';

import '../data/buscador.dart';
import '../location.dart';

/// Resultado especial: el usuario pide volver al GPS.
const Ubicacion usarGps = Ubicacion(0, 0, '__gps__');

class ElegirLugarPage extends StatefulWidget {
  final BuscadorLugares? buscador;

  const ElegirLugarPage({super.key, this.buscador});

  @override
  State<ElegirLugarPage> createState() => _ElegirLugarPageState();
}

class _ElegirLugarPageState extends State<ElegirLugarPage> {
  late final BuscadorLugares _buscador = widget.buscador ?? BuscadorLugares();
  final _texto = TextEditingController();
  Timer? _espera;
  List<Ubicacion> _resultados = const [];
  bool _buscando = false;
  String? _error;

  @override
  void dispose() {
    _espera?.cancel();
    _texto.dispose();
    super.dispose();
  }

  void _alEscribir(String valor) {
    _espera?.cancel();
    _espera = Timer(const Duration(milliseconds: 450), () => _buscar(valor));
  }

  Future<void> _buscar(String valor) async {
    if (valor.trim().length < 3) {
      setState(() => _resultados = const []);
      return;
    }
    setState(() {
      _buscando = true;
      _error = null;
    });
    try {
      final r = await _buscador.buscar(valor);
      if (!mounted || _texto.text != valor) return;
      setState(() => _resultados = r);
    } catch (_) {
      if (mounted) setState(() => _error = 'No se pudo buscar. Comprueba la conexión.');
    } finally {
      if (mounted) setState(() => _buscando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Elegir lugar')),
      body: ListView(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: TextField(
              controller: _texto,
              autofocus: false,
              textInputAction: TextInputAction.search,
              decoration: InputDecoration(
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _buscando
                    ? const Padding(padding: EdgeInsets.all(12), child: SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)))
                    : null,
                hintText: 'Busca una población (p. ej. Tudela)',
                border: const OutlineInputBorder(),
              ),
              onChanged: _alEscribir,
              onSubmitted: _buscar,
            ),
          ),
          if (_error != null) Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: Text(_error!)),
          for (final r in _resultados)
            ListTile(leading: const Icon(Icons.place), title: Text(r.etiqueta), onTap: () => Navigator.pop(context, r)),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.my_location),
            title: const Text('Usar mi ubicación (GPS)'),
            onTap: () => Navigator.pop(context, usarGps),
          ),
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 8, 16, 4),
            child: Text('Zonas con datos oficiales cargados:'),
          ),
          for (final l in lugaresConDatos)
            ListTile(leading: const Icon(Icons.place_outlined), title: Text(l.etiqueta), onTap: () => Navigator.pop(context, l)),
        ],
      ),
    );
  }
}

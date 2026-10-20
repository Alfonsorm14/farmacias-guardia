import 'package:flutter/material.dart';

import '../data/repository.dart';
import '../models.dart';
import '../tiempo.dart';

String _fecha(DateTime d) {
  final m = enMadrid(d);
  return '${m.day}/${m.month}/${m.year}';
}

/// Texto de estado de un ámbito: hasta cuándo hay turnos y si solo una parte de sus zonas los tiene.
String estadoCobertura(Cobertura c, DateTime ahora) {
  if (!c.vigenteEn(ahora)) {
    return c.hasta == null
        ? 'Sin turnos publicados'
        : 'Sin turnos publicados para estas fechas (los últimos, del ${_fecha(c.hasta!)})';
  }
  final hasta = 'Turnos publicados hasta el ${_fecha(c.hasta!)}';
  if (c.parcial) {
    return '$hasta. Solo ${c.zonasConTurnos} de ${c.zonas} zonas tienen turnos publicados para estas fechas.';
  }
  return c.municipal ? '$hasta. Solo el término municipal.' : '$hasta.';
}

/// Lista de ámbitos con su estado (bienvenida y "¿Dónde funciona?").
class ListaCobertura extends StatelessWidget {
  final List<Cobertura> cobertura;
  final DateTime ahora;

  const ListaCobertura({super.key, required this.cobertura, required this.ahora});

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Column(
      children: [
        for (final c in cobertura)
          ListTile(
            leading: Icon(
              !c.vigenteEn(ahora)
                  ? Icons.cloud_off_outlined
                  : c.parcial
                      ? Icons.incomplete_circle
                      : Icons.check_circle_outline,
              color: c.vigenteEn(ahora) && !c.parcial ? tema.colorScheme.primary : tema.colorScheme.outline,
            ),
            title: Text(c.ambito),
            subtitle: Text(estadoCobertura(c, ahora)),
          ),
      ],
    );
  }
}

/// Pantalla "¿Dónde funciona?".
class CoberturaPage extends StatefulWidget {
  final GuardiasRepository repositorio;
  final DateTime Function()? reloj;

  const CoberturaPage({super.key, required this.repositorio, this.reloj});

  @override
  State<CoberturaPage> createState() => _CoberturaPageState();
}

class _CoberturaPageState extends State<CoberturaPage> {
  late final DateTime _ahora = (widget.reloj ?? DateTime.now)();
  late final Future<List<Cobertura>> _cobertura = widget.repositorio.cobertura(_ahora);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('¿Dónde funciona?')),
      body: FutureBuilder<List<Cobertura>>(
        future: _cobertura,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return const Center(child: Text('No se han podido cargar los datos'));
          }
          return ListView(
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 16, 16, 8),
                child: Text(
                  'La app muestra los turnos de guardia que publican las administraciones. Estas son las zonas '
                  'con datos oficiales cargados. Iremos añadiendo más a medida que se publiquen.',
                ),
              ),
              ListaCobertura(cobertura: snap.data!, ahora: _ahora),
            ],
          );
        },
      ),
    );
  }
}

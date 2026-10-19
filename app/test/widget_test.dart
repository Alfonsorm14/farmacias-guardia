import 'dart:convert';
import 'dart:io';

import 'package:farmacias_guardia/data/guardias_engine.dart';
import 'package:farmacias_guardia/data/repository.dart';
import 'package:farmacias_guardia/location.dart';
import 'package:farmacias_guardia/ui/home_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';

Widget _app(GuardiasRepository repo, Ubicacion u, DateTime ahora) => MaterialApp(
      locale: const Locale('es', 'ES'),
      supportedLocales: const [Locale('es', 'ES')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      home: HomePage(repositorio: repo, ubicacionInicial: u, reloj: () => ahora),
    );

void main() {
  late SnapshotRepository repo;

  setUpAll(() async {
    await initializeDateFormatting('es_ES');
    final texto = File('assets/snapshot.json').readAsStringSync();
    repo = SnapshotRepository(GuardiasEngine.desdeJson(jsonDecode(texto) as Map<String, dynamic>));
  });

  testWidgets('Palma de noche muestra las farmacias de guardia', (tester) async {
    await tester.pumpWidget(_app(repo, lugaresConDatos.first, DateTime.utc(2026, 1, 1, 22).toLocal()));
    await tester.pumpAndSettle();
    expect(find.textContaining('REAL VICENS'), findsWidgets);
    expect(find.text('Cómo llegar'), findsWidgets);
  });

  testWidgets('Burgos avisa de que no hay datos oficiales', (tester) async {
    await tester.pumpWidget(_app(repo, const Ubicacion(42.3439, -3.6969, 'Burgos'), DateTime(2026, 10, 19, 22)));
    await tester.pumpAndSettle();
    expect(find.text('Sin datos oficiales para esta zona'), findsOneWidget);
  });

  testWidgets('las pestañas Hoy, Mañana y Pasado cambian la consulta', (tester) async {
    await tester.pumpWidget(_app(repo, lugaresConDatos.first, DateTime(2026, 3, 10, 12)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Mañana'));
    await tester.pumpAndSettle();
    expect(find.textContaining('mié 11'), findsWidgets);
  });
}

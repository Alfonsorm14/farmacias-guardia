import 'dart:convert';
import 'dart:io';

import 'package:farmacias_guardia/data/guardias_engine.dart';
import 'package:farmacias_guardia/data/repository.dart';
import 'package:farmacias_guardia/data/preferencias.dart';
import 'package:farmacias_guardia/location.dart';
import 'package:farmacias_guardia/ui/acerca_de.dart';
import 'package:farmacias_guardia/ui/home_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:shared_preferences/shared_preferences.dart';

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

  testWidgets('la pantalla de fuentes cita las fuentes oficiales y OpenStreetMap', (tester) async {
    await tester.pumpWidget(MaterialApp(home: AcercaDePage(repositorio: repo)));
    await tester.pumpAndSettle();
    expect(find.textContaining('Govern de les Illes Balears'), findsOneWidget);
    expect(find.textContaining('Solo su término municipal'), findsWidgets);
    await tester.scrollUntilVisible(find.textContaining('Servicio de datos de farmacias de guardia'), 200, scrollable: find.byType(Scrollable).first);
    expect(find.textContaining('Solo su término municipal'), findsNWidgets(2));
    await tester.scrollUntilVisible(find.text('Mapa: © colaboradores de OpenStreetMap'), 200, scrollable: find.byType(Scrollable).first);
    expect(find.textContaining('colaboradores de OpenStreetMap'), findsWidgets);
  });

  testWidgets('elegir una fecha en el calendario consulta ese día', (tester) async {
    await tester.pumpWidget(_app(repo, lugaresConDatos.first, DateTime(2026, 3, 10, 12)));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Elegir fecha'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('20'));
    final ok = MaterialLocalizations.of(tester.element(find.byType(DatePickerDialog))).okButtonLabel;
    await tester.tap(find.text(ok));
    await tester.pumpAndSettle();
    expect(find.textContaining('20 de marzo de 2026'), findsOneWidget);
    expect(find.textContaining('vie 20'), findsWidgets);
    // Quitar la fecha vuelve a "Ahora".
    await tester.tap(find.byTooltip('Quitar fecha'));
    await tester.pumpAndSettle();
    expect(find.textContaining('20 de marzo de 2026'), findsNothing);
  });

  test('el último lugar elegido a mano se recuerda; la posición GPS no', () async {
    SharedPreferences.setMockInitialValues({});
    expect(await leerUltimoLugar(), isNull);
    await guardarUltimoLugar(const Ubicacion(40.0, -3.0, 'Tu ubicación', esGps: true));
    expect(await leerUltimoLugar(), isNull);
    await guardarUltimoLugar(const Ubicacion(42.0617, -1.6046, 'Tudela'));
    final u = await leerUltimoLugar();
    expect(u?.etiqueta, 'Tudela');
    expect(u?.lat, 42.0617);
  });
}

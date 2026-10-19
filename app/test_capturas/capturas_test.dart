// Capturas de pantalla para revisión visual (no forma parte de la batería de tests).
// flutter test test_capturas --update-goldens
import 'dart:convert';
import 'dart:io';

import 'package:farmacias_guardia/data/guardias_engine.dart';
import 'package:farmacias_guardia/data/repository.dart';
import 'package:farmacias_guardia/location.dart';
import 'package:farmacias_guardia/ui/acerca_de.dart';
import 'package:farmacias_guardia/ui/home_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';

Future<void> _fuente(String familia, List<String> ficheros) async {
  final loader = FontLoader(familia);
  for (final f in ficheros) {
    loader.addFont(Future.value(ByteData.view(File(f).readAsBytesSync().buffer)));
  }
  await loader.load();
}

Widget _app(Widget home) => MaterialApp(
      debugShowCheckedModeBanner: false,
      locale: const Locale('es', 'ES'),
      supportedLocales: const [Locale('es', 'ES')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      theme: ThemeData(colorSchemeSeed: const Color(0xFF0B8A4A), useMaterial3: true, fontFamily: 'Roboto'),
      home: home,
    );

void main() {
  late SnapshotRepository repo;
  setUpAll(() async {
    await initializeDateFormatting('es_ES');
    const base = '/opt/flutter/bin/cache/artifacts/material_fonts';
    await _fuente('Roboto', ['$base/Roboto-Regular.ttf', '$base/Roboto-Medium.ttf', '$base/Roboto-Bold.ttf']);
    await _fuente('MaterialIcons', ['$base/MaterialIcons-Regular.otf']);
    repo = SnapshotRepository(GuardiasEngine.desdeJson(jsonDecode(File('assets/snapshot.json').readAsStringSync()) as Map<String, dynamic>));
  });

  Future<void> captura(WidgetTester tester, Widget w, String nombre, {Future<void> Function()? accion}) async {
    tester.view.physicalSize = const Size(1080, 2280);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(_app(w));
    await tester.pumpAndSettle();
    if (accion != null) await accion();
    await expectLater(find.byType(MaterialApp), matchesGoldenFile('capturas/$nombre.png'));
  }

  testWidgets('Palma ahora', (t) => captura(t, HomePage(repositorio: repo, ubicacionInicial: lugaresConDatos.first, reloj: () => DateTime(2026, 10, 20, 23)), 'palma_ahora'));
  testWidgets('Mula hoy', (t) => captura(t, HomePage(repositorio: repo, ubicacionInicial: const Ubicacion(38.0413, -1.4904, 'Mula'), reloj: () => DateTime(2026, 10, 20, 12)), 'mula_hoy', accion: () async {
        await t.tap(find.text('Hoy'));
        await t.pumpAndSettle();
      }));
  testWidgets('Madrid fecha pasada', (t) => captura(t, HomePage(repositorio: repo, ubicacionInicial: lugaresConDatos[12], reloj: () => DateTime(2026, 10, 20, 12)), 'madrid_hoy', accion: () async {
        await t.tap(find.text('Hoy'));
        await t.pumpAndSettle();
      }));
  testWidgets('Fuentes', (t) => captura(t, AcercaDePage(repositorio: repo), 'fuentes'));
  testWidgets('Pamplona marzo', (t) => captura(t, HomePage(repositorio: repo, ubicacionInicial: lugaresConDatos[9], reloj: () => DateTime(2026, 3, 15, 12)), 'pamplona_marzo', accion: () async {
        await t.tap(find.text('Hoy'));
        await t.pumpAndSettle();
      }));
  testWidgets('Burgos', (t) => captura(t, HomePage(repositorio: repo, ubicacionInicial: const Ubicacion(42.3439, -3.6969, 'Burgos'), reloj: () => DateTime(2026, 10, 20, 12)), 'burgos'));
}

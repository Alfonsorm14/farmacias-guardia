// Capturas para la ficha de Google Play (1080x1920, 9:16). No forma parte de la batería de tests.
// flutter test test_capturas/play_test.dart --update-goldens  ->  docs/play/*.png
import 'dart:convert';
import 'dart:io';

import 'package:farmacias_guardia/data/guardias_engine.dart';
import 'package:farmacias_guardia/data/repository.dart';
import 'package:farmacias_guardia/location.dart';
import 'package:farmacias_guardia/ui/acerca_de.dart';
import 'package:farmacias_guardia/ui/bienvenida.dart';
import 'package:farmacias_guardia/ui/cobertura.dart';
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
    tester.view.physicalSize = const Size(1080, 1920);
    tester.view.devicePixelRatio = 2.625;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(_app(w));
    await tester.pumpAndSettle();
    if (accion != null) await accion();
    await expectLater(find.byType(MaterialApp), matchesGoldenFile('../../docs/play/$nombre.png'));
  }

  Ubicacion lugar(String etiqueta) => lugaresConDatos.firstWhere((u) => u.etiqueta.startsWith(etiqueta));

  testWidgets('1 Palma de noche', (t) => captura(t, HomePage(repositorio: repo, ubicacionInicial: lugar('Palma'), reloj: () => DateTime(2026, 10, 20, 23)), '1_palma_ahora'));
  testWidgets('2 Pamplona de noche', (t) => captura(t, HomePage(repositorio: repo, ubicacionInicial: lugar('Pamplona'), reloj: () => DateTime(2026, 10, 20, 22, 30)), '2_pamplona_ahora'));
  testWidgets('3 Madrid ahora', (t) => captura(t, HomePage(repositorio: repo, ubicacionInicial: lugar('Madrid (Puerta'), reloj: () => DateTime(2026, 10, 20, 12)), '3_madrid_ahora'));
  testWidgets('4 Dónde funciona', (t) => captura(t, CoberturaPage(repositorio: repo, reloj: () => DateTime(2026, 10, 20, 12)), '4_donde_funciona'));
  testWidgets('5 Bienvenida', (t) => captura(t, BienvenidaPage(repositorio: repo, alTerminar: () {}, reloj: () => DateTime(2026, 10, 20, 12)), '5_bienvenida'));
  testWidgets('6 Fuentes', (t) => captura(t, AcercaDePage(repositorio: repo), '6_fuentes'));
}

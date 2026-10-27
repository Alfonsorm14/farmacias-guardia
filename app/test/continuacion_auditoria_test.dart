import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:farmacias_guardia/data/guardias_engine.dart';
import 'package:farmacias_guardia/data/repository.dart';
import 'package:farmacias_guardia/location.dart';
import 'package:farmacias_guardia/models.dart';
import 'package:farmacias_guardia/tiempo.dart';
import 'package:farmacias_guardia/ui/guardia_card.dart';
import 'package:farmacias_guardia/ui/home_page.dart';
import 'package:farmacias_guardia/ui/mapa.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:shared_preferences/shared_preferences.dart';

final fixture = jsonDecode(
  File('test/fixtures/paridad_elegibilidad.json').readAsStringSync(),
) as Map<String, dynamic>;
GuardiasEngine engine() =>
    GuardiasEngine.desdeJson(fixture['snapshot'] as Map<String, dynamic>);

class RecordingRepository extends SnapshotRepository {
  final calls = <DateTime>[];
  RecordingRepository() : super(engine());

  @override
  Future<ResultadoGuardias> ahora(double lat, double lon, DateTime instante) {
    calls.add(instante);
    return super.ahora(lat, lon, instante);
  }
}

class DeferredRepository extends RecordingRepository {
  final pending = Completer<ResultadoGuardias>();

  @override
  Future<ResultadoGuardias> ahora(double lat, double lon, DateTime instante) {
    if (calls.isEmpty) {
      calls.add(instante);
      return pending.future;
    }
    return super.ahora(lat, lon, instante);
  }
}

Widget app(Widget home, {double scale = 1}) => MaterialApp(
  locale: const Locale('es', 'ES'),
  supportedLocales: const [Locale('es', 'ES')],
  localizationsDelegates: const [
    GlobalMaterialLocalizations.delegate,
    GlobalWidgetsLocalizations.delegate,
    GlobalCupertinoLocalizations.delegate,
  ],
  builder: (context, child) => MediaQuery(
    data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)),
    child: child!,
  ),
  home: home,
);

void main() {
  setUpAll(() async => initializeDateFormatting('es_ES'));
  setUp(() => SharedPreferences.setMockInitialValues({}));

  for (final c in fixture['cases'] as List) {
    test('paridad de elegibilidad snapshot/API: ${c['name']}', () async {
      final expected = c['response'] as Map<String, dynamic>;
      final day = c.containsKey('fecha');
      final date = DateTime.parse((day ? c['fecha'] : c['at']) as String);
      final start = day
          ? inicioDiaMadrid(date.year, date.month, date.day)
          : date;
      final local = engine().consultar(
        lat: 40,
        lon: -3,
        desde: start,
        hasta: day
            ? inicioDiaMadrid(date.year, date.month, date.day + 1)
            : null,
      );
      final remote = ApiRepository(
        'https://example.org',
        MockClient((_) async => http.Response(jsonEncode(expected), 200)),
      );
      final api = day
          ? await remote.dia(40, -3, date)
          : await remote.ahora(40, -3, date);
      for (final result in [local, api]) {
        expect(
          result.guardias.map((g) => g.farmacia.id),
          (expected['guardias'] as List).map((g) => g['farmacia']['id']),
        );
        expect(
          result.numeroSinCoordenadas,
          expected['farmacias_sin_coordenadas'],
        );
        expect(result.mensaje, expected['mensaje']);
        expect(
          result.proximoCambio,
          expected['proximo_cambio'] == null
              ? null
              : DateTime.parse(expected['proximo_cambio'] as String).toUtc(),
        );
      }
    });
  }

  for (final start in [
    DateTime.utc(2026, 10, 27, 8, 59, 59),
    DateTime.utc(2026, 10, 27, 9, 59, 59),
  ]) {
    testWidgets('Ahora se actualiza en inicio/fin de turno desde $start', (
      tester,
    ) async {
      final clockOrigin = tester.binding.clock.now();
      DateTime now() =>
          start.add(tester.binding.clock.now().difference(clockOrigin));
      final boundary = start.add(const Duration(seconds: 1));
      final repo = RecordingRepository();
      await tester.pumpWidget(
        app(
          HomePage(
            repositorio: repo,
            ubicacionInicial: const Ubicacion(40, -3, 'Prueba'),
            reloj: now,
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(repo.calls, hasLength(1));
      await tester.pump(
        boundary.difference(now()) - const Duration(milliseconds: 1),
      );
      expect(repo.calls, hasLength(1));
      await tester.pump(const Duration(milliseconds: 1));
      await tester.pumpAndSettle();
      expect(repo.calls, hasLength(2));
      expect(repo.calls.last, boundary);
      expect(
        find.textContaining(start.hour == 8 ? 'Diurna' : 'Nocturna'),
        findsWidgets,
      );
      await tester.pumpWidget(const SizedBox());
    });
  }

  testWidgets('Hoy cancela el refresco de Ahora y dispose no deja timers', (
    tester,
  ) async {
    var now = DateTime.utc(2026, 10, 27, 9, 59, 59);
    final repo = RecordingRepository();
    await tester.pumpWidget(
      app(
        HomePage(
          repositorio: repo,
          ubicacionInicial: const Ubicacion(40, -3, 'Prueba'),
          reloj: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Hoy'));
    await tester.pumpAndSettle();
    now = now.add(const Duration(seconds: 2));
    await tester.pump(const Duration(seconds: 2));
    expect(repo.calls, hasLength(1));
    await tester.tap(find.text('Ahora'));
    await tester.pumpAndSettle();
    expect(repo.calls, hasLength(2));
    await tester.pumpWidget(const SizedBox());
    now = now.add(const Duration(hours: 2));
    await tester.pump(const Duration(hours: 2));
    expect(repo.calls, hasLength(2));
  });

  testWidgets(
    'pausa cancela el timer y reanudar consulta con el reloj actual',
    (tester) async {
      final origin = tester.binding.clock.now();
      final start = DateTime.utc(2026, 10, 27, 9, 59, 59);
      DateTime now() =>
          start.add(tester.binding.clock.now().difference(origin));
      final repo = RecordingRepository();
      await tester.pumpWidget(
        app(
          HomePage(
            repositorio: repo,
            ubicacionInicial: const Ubicacion(40, -3, 'Prueba'),
            reloj: now,
          ),
        ),
      );
      await tester.pumpAndSettle();
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump(const Duration(seconds: 2));
      expect(repo.calls, hasLength(1));
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(repo.calls, hasLength(2));
      expect(repo.calls.last, isNot(equals(start)));
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('una respuesta antigua no rearma el timer tras elegir Hoy', (
    tester,
  ) async {
    final now = DateTime.utc(2026, 10, 27, 9, 59, 59);
    final repo = DeferredRepository();
    await tester.pumpWidget(
      app(
        HomePage(
          repositorio: repo,
          ubicacionInicial: const Ubicacion(40, -3, 'Prueba'),
          reloj: () => now,
        ),
      ),
    );
    await tester.pump();
    await tester.tap(find.text('Hoy'));
    await tester.pumpAndSettle();
    repo.pending.complete(engine().consultar(lat: 40, lon: -3, desde: now));
    await tester.pump();
    await tester.pump(const Duration(seconds: 2));
    expect(repo.calls, hasLength(1));
    await tester.pumpWidget(const SizedBox());
  });

  for (final empty in [false, true]) {
    testWidgets(
      'la API muestra el conteo sin coordenadas, lista vacía: $empty',
      (tester) async {
        final payload = Map<String, dynamic>.from(
          (fixture['cases'] as List)[1]['response'] as Map,
        );
        if (empty) payload['guardias'] = <dynamic>[];
        final repo = ApiRepository(
          'https://example.org',
          MockClient((_) async => http.Response(jsonEncode(payload), 200)),
        );
        await tester.pumpWidget(
          app(
            HomePage(
              repositorio: repo,
              ubicacionInicial: const Ubicacion(40, -3, 'Prueba'),
              reloj: () => DateTime.utc(2026, 10, 27, 9, 30),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(
          find.text('1 de guardia en tu zona sin situar en el mapa'),
          findsOneWidget,
        );
        await tester.pumpWidget(const SizedBox());
      },
    );
  }

  for (final firstFails in [false, true]) {
    testWidgets('respaldo de un minuto y recuperación de error: $firstFails', (
      tester,
    ) async {
      var calls = 0;
      final payload = Map<String, dynamic>.from(
        (fixture['cases'] as List)[1]['response'] as Map,
      )..remove('proximo_cambio');
      final repo = ApiRepository(
        'https://example.org',
        MockClient((_) async {
          calls++;
          return calls == 1 && firstFails
              ? http.Response('Error de prueba', 500)
              : http.Response(jsonEncode(payload), 200);
        }),
      );
      final origin = tester.binding.clock.now();
      final start = DateTime.utc(2026, 10, 27, 9, 30);
      DateTime now() =>
          start.add(tester.binding.clock.now().difference(origin));
      await tester.pumpWidget(
        app(
          HomePage(
            repositorio: repo,
            ubicacionInicial: const Ubicacion(40, -3, 'Prueba'),
            reloj: now,
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(calls, 1);
      if (firstFails) {
        expect(find.text('No se han podido cargar los datos'), findsOneWidget);
      }
      await tester.pump(
        start.add(const Duration(minutes: 1)).difference(now()),
      );
      await tester.pumpAndSettle();
      expect(calls, 2);
      expect(find.byType(GuardiaCard), findsOneWidget);
      expect(find.text('No se han podido cargar los datos'), findsNothing);
      await tester.pumpWidget(const SizedBox());
    });
  }

  testWidgets('tarjeta con acciones legibles a escala 2 y anchura 320', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final result = engine().consultar(
      lat: 40,
      lon: -3,
      desde: DateTime.utc(2026, 10, 27, 9, 30),
    );
    await tester.pumpWidget(
      app(
        Scaffold(
          body: SingleChildScrollView(
            child: GuardiaCard(
              guardia: result.guardias.first,
              ahora: DateTime.utc(2026, 10, 27, 9, 30),
            ),
          ),
        ),
        scale: 2,
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.text('910000000'), findsOneWidget);
    expect(find.text('Cómo llegar'), findsOneWidget);
    expect(find.byTooltip('Compartir'), findsOneWidget);
  });

  testWidgets('Home conserva todas las vistas a escala 2 y anchura 320', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      app(
        HomePage(
          repositorio: RecordingRepository(),
          ubicacionInicial: const Ubicacion(40, -3, 'Prueba'),
          reloj: () => DateTime.utc(2026, 10, 27, 9, 30),
        ),
        scale: 2,
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    for (final view in ['Ahora', 'Hoy', 'Mañana', 'Pasado']) {
      expect(find.text(view), findsOneWidget);
    }
    await tester.tap(find.text('Mañana'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('marcador con nombre y acción accesibles', (tester) async {
    tester.view.physicalSize = const Size(320, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final semantics = tester.ensureSemantics();
    final guards = engine()
        .consultar(lat: 40, lon: -3, desde: DateTime.utc(2026, 10, 27, 9, 30))
        .guardias;
    await tester.pumpWidget(
      app(
        Scaffold(
          body: MapaGuardias(
            ubicacion: const Ubicacion(40, -3, 'Prueba'),
            guardias: guards,
          ),
        ),
        scale: 2,
      ),
    );
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.bySemanticsLabel('Farmacia Localizada'), findsOneWidget);
    expect(
      tester.getSemantics(find.bySemanticsLabel('Farmacia Localizada')),
      matchesSemantics(
        label: 'Farmacia Localizada',
        isButton: true,
        hasTapAction: true,
      ),
    );
    await tester.tap(find.bySemanticsLabel('Farmacia Localizada'));
    await tester.pumpAndSettle();
    expect(find.byType(GuardiaCard), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    semantics.dispose();
  });
}

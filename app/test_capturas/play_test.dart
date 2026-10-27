// Generador optativo. Ejecutar scripts/generar_capturas.sh o .ps1 desde la raíz.
// No se importa en la app ni modifica sus dependencias o configuración.
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:farmacias_guardia/data/guardias_engine.dart';
import 'package:farmacias_guardia/data/repository.dart';
import 'package:farmacias_guardia/location.dart';
import 'package:farmacias_guardia/ui/guardia_card.dart';
import 'package:farmacias_guardia/ui/home_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'soporte/escenario_play.dart';
import 'soporte/grafico_play.dart';

const captureEnabled = bool.fromEnvironment('PLAY_CAPTURAS');
const outputRoot = '../play/capturas';
const devices = [
  (name: 'telefono', logical: Size(432, 768), pixels: Size(1080, 1920)),
  (name: 'tablet_7', logical: Size(600, 900), pixels: Size(1280, 1920)),
  (name: 'tablet_10', logical: Size(800, 1280), pixels: Size(1600, 2560)),
];
const screens = [
  '01_ahora_lista',
  '02_mapa',
  '03_manana',
  '04_detalle',
  '05_selector_lugar',
  '06_fuentes',
  '07_privacidad',
];
const boundaryKey = ValueKey('play-boundary');

Future<void> loadCaptureFonts() async {
  // flutter_tester está dentro del SDK tanto en Linux como en Windows.
  var sdk = File(Platform.resolvedExecutable).parent;
  while (!Directory('${sdk.path}/bin/cache/artifacts/material_fonts')
      .existsSync()) {
    if (sdk.parent.path == sdk.path) {
      throw StateError(
        'No se encuentran las fuentes incluidas en el SDK Flutter.',
      );
    }
    sdk = sdk.parent;
  }
  final base = '${sdk.path}/bin/cache/artifacts/material_fonts';
  for (final entry in {
    'Roboto': ['Roboto-Regular.ttf', 'Roboto-Medium.ttf', 'Roboto-Bold.ttf'],
    'MaterialIcons': ['MaterialIcons-Regular.otf'],
  }.entries) {
    final loader = FontLoader(entry.key);
    for (final name in entry.value) {
      final bytes = File('$base/$name').readAsBytesSync();
      loader.addFont(Future.value(ByteData.sublistView(bytes)));
    }
    await loader.load();
  }
}

Widget captureApp(Widget home, Brightness brightness, {bool map = false}) =>
    RepaintBoundary(
      key: boundaryKey,
      child: MaterialApp(
        debugShowCheckedModeBanner: false,
        locale: const Locale('es', 'ES'),
        supportedLocales: const [Locale('es', 'ES')],
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        theme: ThemeData(
          colorSchemeSeed: const Color(0xFF0B8A4A),
          brightness: brightness,
          useMaterial3: true,
          fontFamily: 'Roboto',
          platform: TargetPlatform.android,
        ),
        builder: (context, child) => Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(child: child!),
            Material(
              color: Theme.of(context).colorScheme.surfaceContainer,
              child: Padding(
                padding: const EdgeInsets.all(8),
                child: Text(
                  'Demostración · 27/10/2026, 12:00 · Datos anonimizados'
                  '${map ? '\nFondo esquemático · Sin cartografía real' : ''}',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.labelSmall,
                ),
              ),
            ),
          ],
        ),
        home: home,
      ),
    );

Future<void> savePng(WidgetTester tester, String name, Size pixels) async {
  expect(
    tester.takeException(),
    isNull,
    reason: 'No debe haber desbordes ni errores',
  );
  final boundary = tester.renderObject<RenderRepaintBoundary>(
    find.byKey(boundaryKey),
  );
  await tester.runAsync(() async {
    final image = await boundary.toImage(
      pixelRatio: pixels.width / boundary.size.width,
    );
    expect(Size(image.width.toDouble(), image.height.toDouble()), pixels);
    final data = await image.toByteData(format: ui.ImageByteFormat.png);
    final file = File('$outputRoot/$name.png');
    await file.parent.create(recursive: true);
    await file.writeAsBytes(data!.buffer.asUint8List(), flush: true);
    image.dispose();
  });
}

void main() {
  if (!captureEnabled) {
    test(
      'capturas desactivadas: usar scripts/generar_capturas',
      () {},
      skip: true,
    );
    return;
  }
  final location = lugaresConDatos.firstWhere((u) => u.etiqueta == 'Palma');
  late CaptureRepository repository;
  late CaptureHttpOverrides network;
  late Uint8List icon;
  late Uint8List lightTile;
  late Uint8List darkTile;
  late BuiltInMapCachingProvider mapCache;
  final previousOverrides = HttpOverrides.current;

  setUpAll(() async {
    await initializeDateFormatting('es_ES');
    final cacheDirectory = await Directory.systemTemp.createTemp(
      'play-capturas-',
    );
    mapCache = BuiltInMapCachingProvider.getOrCreateInstance(
      cacheDirectory: cacheDirectory.path,
      maxCacheSize: null,
      overrideFreshAge: const Duration(days: 1),
      readOnly: true,
    );
    await mapCache.getTile('inicializar');
    await loadCaptureFonts();
    final snapshot = jsonDecode(
      File('assets/snapshot.json').readAsStringSync(),
    ) as Map<String, dynamic>;
    repository = CaptureRepository(
      SnapshotRepository(GuardiasEngine.desdeJson(snapshot), null, ''),
    );
    lightTile = await createLocalTile();
    darkTile = await createLocalTile(dark: true);
    network = CaptureHttpOverrides(lightTile);
    icon = File('assets/icon/icono_play_512.png').readAsBytesSync();
  });
  tearDownAll(() async => mapCache.destroy(deleteCache: true));
  setUp(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          const MethodChannel('plugins.flutter.io/shared_preferences'),
          (call) async => call.method == 'getAll' ? <String, Object>{} : true,
        );
    HttpOverrides.global = network;
  });
  tearDown(() => HttpOverrides.global = previousOverrides);

  test('el snapshot contiene guardias en Palma ahora y mañana, sin datos personales', () async {
    for (final result in [
      await repository.ahora(location.lat, location.lon, captureInstant),
      await repository.dia(location.lat, location.lon, DateTime(2026, 10, 28)),
    ]) {
      expect(result.cobertura, isTrue);
      expect(result.guardias, isNotEmpty);
      for (final g in result.guardias) {
        expect(g.farmacia.titular, startsWith('de ejemplo '));
        expect(g.farmacia.direccion, 'Dirección de demostración');
        expect(g.farmacia.telefonoParaLlamar, isNull);
      }
    }
    await expectLater(
      HttpClient().getUrl(Uri.parse('https://example.org')),
      throwsStateError,
    );
  });

  for (final device in devices) {
    for (final brightness in Brightness.values) {
      final theme = brightness == Brightness.light ? 'claro' : 'oscuro';
      for (final screen in screens) {
        testWidgets('${device.name}/$theme/$screen', (tester) async {
          debugDisableShadows = false;
          addTearDown(() => debugDisableShadows = true);
          PaintingBinding.instance.imageCache.clear();
          network = CaptureHttpOverrides(
            brightness == Brightness.dark ? darkTile : lightTile,
          );
          HttpOverrides.global = network;
          tester.view.physicalSize = device.pixels;
          tester.view.devicePixelRatio =
              device.pixels.width / device.logical.width;
          addTearDown(tester.view.reset);
          final isMap = screen == '02_mapa' || screen == '04_detalle';
          await tester.pumpWidget(
            captureApp(
              HomePage(
                repositorio: repository,
                ubicacionInicial: location,
                reloj: () => captureInstant,
              ),
              brightness,
              map: isMap,
            ),
          );
          await tester.pumpAndSettle();
          expect(find.byType(GuardiaCard), findsWidgets);
          if (isMap) {
            await tester.tap(find.byTooltip('Ver mapa'));
            await tester.pumpAndSettle();
            // Esperar a la E/S local y a la decodificación, no a un plazo
            // arbitrario: evita capturar un mapa vacío según la carga del equipo.
            for (var attempt = 0; attempt < 100; attempt++) {
              await tester.runAsync(() async {
                await Future<void>.delayed(const Duration(milliseconds: 20));
              });
              await tester.pump(const Duration(milliseconds: 100));
              if (PaintingBinding.instance.imageCache.pendingImageCount == 0 &&
                  network.requests > 0) {
                break;
              }
            }
            await tester.pumpAndSettle();
            expect(network.requests, greaterThan(0));
            expect(PaintingBinding.instance.imageCache.pendingImageCount, 0);
            expect(
              tester
                  .widgetList<RawImage>(find.byType(RawImage))
                  .where((image) => image.image != null),
              isNotEmpty,
            );
          }
          switch (screen) {
            case '03_manana':
              await tester.tap(find.text('Mañana'));
              await tester.pumpAndSettle();
              expect(find.byType(GuardiaCard), findsWidgets);
            case '04_detalle':
              final result = await repository.ahora(
                location.lat,
                location.lon,
                captureInstant,
              );
              final context = tester.element(find.byType(HomePage));
              // La misma ficha y contenedor del mapa, con reloj fijo en vez de
              // DateTime.now(): no se altera el reloj ni el código de producción.
              if (context.mounted) {
                showModalBottomSheet<void>(
                  context: context,
                  isScrollControlled: true,
                  builder: (_) => SafeArea(
                    child: SingleChildScrollView(
                      child: GuardiaCard(
                        guardia: result.guardias.first,
                        ahora: captureInstant,
                      ),
                    ),
                  ),
                );
              }
              await tester.pumpAndSettle();
              expect(find.byType(GuardiaCard), findsOneWidget);
            case '05_selector_lugar':
              await tester.tap(find.text('Cambiar'));
              await tester.pumpAndSettle();
              expect(find.text('Elegir lugar'), findsOneWidget);
            case '06_fuentes' || '07_privacidad':
              await tester.tap(find.byTooltip('Más opciones'));
              await tester.pumpAndSettle();
              await tester.tap(find.text('Fuentes y privacidad'));
              await tester.pumpAndSettle();
              expect(find.text('Turnos de guardia'), findsOneWidget);
              if (screen == '07_privacidad') {
                await tester.drag(
                  find.byType(ListView).last,
                  const Offset(0, -2400),
                );
                await tester.pumpAndSettle();
                expect(
                  find.text('Política de privacidad completa').hitTestable(),
                  findsOneWidget,
                );
              }
          }
          await savePng(
            tester,
            '${device.name}/${theme}_$screen',
            device.pixels,
          );
          debugDisableShadows = true;
          await tester.pumpWidget(const SizedBox.shrink());
          await tester.pumpAndSettle();
        });
      }
    }
  }

  testWidgets('gráfico de funciones 1024x500 e icono existente 512x512', (
    tester,
  ) async {
    debugDisableShadows = false;
    addTearDown(() => debugDisableShadows = true);
    tester.view.physicalSize = const Size(1024, 500);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      Directionality(
        textDirection: TextDirection.ltr,
        child: RepaintBoundary(
          key: boundaryKey,
          child: FeatureGraphic(icon: icon),
        ),
      ),
    );
    await tester.runAsync(() async {
      await Future<void>.delayed(const Duration(milliseconds: 100));
    });
    await tester.pumpAndSettle();
    await savePng(tester, 'grafico_funciones_1024x500', const Size(1024, 500));
    await tester.runAsync(() async {
      final codec = await ui.instantiateImageCodec(icon);
      final frame = await codec.getNextFrame();
      expect(frame.image.width, 512);
      expect(frame.image.height, 512);
      frame.image.dispose();
      codec.dispose();
    });
    await tester.runAsync(
      () => File('$outputRoot/icono_512x512.png').writeAsBytes(icon),
    );
    debugDisableShadows = true;
  });
}

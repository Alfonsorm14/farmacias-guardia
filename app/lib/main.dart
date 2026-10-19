import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'data/repository.dart';
import 'ui/home_page.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('es_ES');
  runApp(FarmaciasGuardiaApp(repositorio: GuardiasRepository.crear()));
}

class FarmaciasGuardiaApp extends StatelessWidget {
  final GuardiasRepository repositorio;

  const FarmaciasGuardiaApp({super.key, required this.repositorio});

  @override
  Widget build(BuildContext context) {
    const verde = Color(0xFF0B8A4A);
    return MaterialApp(
      title: 'Farmacias de guardia',
      debugShowCheckedModeBanner: false,
      locale: const Locale('es', 'ES'),
      supportedLocales: const [Locale('es', 'ES')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      theme: ThemeData(colorSchemeSeed: verde, useMaterial3: true),
      darkTheme: ThemeData(colorSchemeSeed: verde, brightness: Brightness.dark, useMaterial3: true),
      home: HomePage(repositorio: repositorio),
    );
  }
}

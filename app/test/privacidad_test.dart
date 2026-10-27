import 'package:farmacias_guardia/data/repository.dart';
import 'package:farmacias_guardia/models.dart';
import 'package:farmacias_guardia/ui/acerca_de.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class PrivacyRepository extends SnapshotRepository {
  @override
  Future<List<Fuente>> fuentes() async => const [];
}

void main() {
  testWidgets(
    'privacidad explica cálculo local y comunicaciones con terceros',
    (tester) async {
      await tester.pumpWidget(
        MaterialApp(home: AcercaDePage(repositorio: PrivacyRepository())),
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.textContaining('ningún servidor propio'),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      expect(
        find.textContaining('guardias se calculan en el teléfono'),
        findsOneWidget,
      );
      expect(
        find.textContaining('IGN recibe tu dirección IP y la zona mostrada'),
        findsOneWidget,
      );
      expect(
        find.textContaining('texto que escribes se envía a CartoCiudad'),
        findsOneWidget,
      );
      expect(
        find.textContaining('Google Maps solo cuando pulsas «Cómo llegar»'),
        findsOneWidget,
      );
      expect(
        find.textContaining('Sin registro, sin publicidad, sin analítica'),
        findsOneWidget,
      );
    },
  );
}

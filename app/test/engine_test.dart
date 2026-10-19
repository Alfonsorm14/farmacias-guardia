import 'dart:convert';
import 'dart:io';

import 'package:farmacias_guardia/data/guardias_engine.dart';
import 'package:farmacias_guardia/models.dart';
import 'package:flutter_test/flutter_test.dart';

/// Pruebas del motor sobre la instantánea real (assets/snapshot.json).
void main() {
  late GuardiasEngine motor;

  setUpAll(() {
    final texto = File('assets/snapshot.json').readAsStringSync();
    motor = GuardiasEngine.desdeJson(jsonDecode(texto) as Map<String, dynamic>);
  });

  test('carga la instantánea completa', () {
    expect(motor.farmacias.length, greaterThan(800));
    expect(motor.turnos.length, greaterThan(50000));
    expect(motor.zonas, contains('SANT ANTONI'));
  });

  test('Palma, 1 de enero de 2026 a las 23:00: las tres nocturnas', () {
    final r = motor.consultar(lat: 39.5696, lon: 2.6502, desde: DateTime.utc(2026, 1, 1, 22), radioKm: 15);
    expect(r.cobertura, isTrue);
    final titulares = r.guardias.map((g) => g.farmacia.titular).toSet();
    expect(titulares, containsAll(['ALCOVER CASASNOVAS, R', 'REAL VICENS', 'GOMEZ GARCIA']));
    expect(r.guardias.every((g) => g.turno.activoEn(DateTime.utc(2026, 1, 1, 22))), isTrue);
    // Ordenadas por distancia
    for (var i = 1; i < r.guardias.length; i++) {
      expect(r.guardias[i].distanciaKm, greaterThanOrEqualTo(r.guardias[i - 1].distanciaKm));
    }
  });

  test('Sant Antoni, 1 de enero de 2026: Bru Bonilla de día y de noche', () {
    final r = motor.consultar(
        lat: 38.9806, lon: 1.3036, desde: DateTime.utc(2025, 12, 31, 23), hasta: DateTime.utc(2026, 1, 1, 23), radioKm: 6);
    final bru = r.guardias.where((g) => g.farmacia.titular == 'BRU BONILLA').map((g) => g.turno.tipo).toSet();
    expect(bru, containsAll([TipoTurno.diurna, TipoTurno.nocturna]));
  });

  test('Pamplona tiene guardias de Navarra con coordenadas oficiales', () {
    final r = motor.consultar(
        lat: 42.8169, lon: -1.6432, desde: DateTime.utc(2026, 10, 18, 22), hasta: DateTime.utc(2026, 10, 19, 22), radioKm: 10);
    expect(r.cobertura, isTrue);
    expect(r.guardias, isNotEmpty);
    expect(r.guardias.every((g) => g.farmacia.id.startsWith('NA:') && !g.farmacia.ubicacionAproximada), isTrue);
  });

  test('Madrid ciudad sí; Alcalá de Henares no hereda las guardias de la capital', () {
    final madrid = motor.consultar(lat: 40.4168, lon: -3.7038, desde: DateTime.utc(2026, 10, 20, 10));
    expect(madrid.cobertura, isTrue);
    expect(madrid.guardias, isNotEmpty);
    expect(madrid.datosHasta!.isAfter(DateTime.utc(2026, 10, 31)), isTrue);
    final alcala = motor.consultar(lat: 40.4818, lon: -3.3643, desde: DateTime.utc(2026, 10, 20, 10));
    expect(alcala.cobertura, isFalse);
  });

  test('Madrid en noviembre: aún no publicado, no "sin guardia"', () {
    final r = motor.consultar(lat: 40.4168, lon: -3.7038, desde: DateTime.utc(2026, 11, 5, 10));
    expect(r.cobertura, isTrue);
    expect(r.guardias, isEmpty);
    expect(r.mensaje, 'Aún no hay turnos oficiales publicados para esta fecha');
  });

  test('Burgos no tiene cobertura', () {
    final r = motor.consultar(lat: 42.3439, lon: -3.6969, desde: DateTime.utc(2026, 10, 19, 20));
    expect(r.cobertura, isFalse);
    expect(r.mensaje, 'Sin datos oficiales para esta zona');
    expect(r.guardias, isEmpty);
  });

  test('fuera del año publicado: cobertura sí, guardias no', () {
    final r = motor.consultar(lat: 39.5696, lon: 2.6502, desde: DateTime.utc(2030, 6, 1, 12));
    expect(r.cobertura, isTrue);
    expect(r.guardias, isEmpty);
    expect(r.mensaje, 'Aún no hay turnos oficiales publicados para esta fecha');
  });

  test('una farmacia en varios cuadrantes a la misma hora sale una vez', () {
    final r = motor.consultar(lat: 39.5696, lon: 2.6502, desde: DateTime.utc(2026, 1, 1, 22), radioKm: 40);
    final claves = r.guardias.map((g) => '${g.farmacia.id}|${g.turno.inicio}|${g.turno.fin}').toList();
    expect(claves.toSet().length, claves.length);
  });

  test('distanciaKm', () {
    expect(distanciaKm(39.5696, 2.6502, 39.5696, 2.6502), 0);
    expect(distanciaKm(37.9922, -1.1307, 37.6257, -0.9966), closeTo(42.7, 1.5));
  });
}

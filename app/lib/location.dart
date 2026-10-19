/// Ubicación del usuario: GPS o lugar elegido a mano.
library;

import 'package:geolocator/geolocator.dart';

class Ubicacion {
  final double lat;
  final double lon;
  final String etiqueta;
  final bool esGps;

  const Ubicacion(this.lat, this.lon, this.etiqueta, {this.esGps = false});
}

/// Lugares de prueba en las comunidades con datos oficiales cargados.
const List<Ubicacion> lugaresConDatos = [
  Ubicacion(39.5696, 2.6502, 'Palma'),
  Ubicacion(38.9067, 1.4206, 'Eivissa'),
  Ubicacion(39.8885, 4.2658, 'Maó'),
  Ubicacion(39.6052, 3.3862, 'Cala Millor'),
  Ubicacion(38.7067, 1.4320, 'Formentera'),
  Ubicacion(37.9922, -1.1307, 'Murcia'),
  Ubicacion(37.6257, -0.9966, 'Cartagena'),
  Ubicacion(37.6772, -1.7006, 'Lorca'),
  Ubicacion(37.7280, -0.8440, 'La Manga del Mar Menor'),
  Ubicacion(42.8169, -1.6432, 'Pamplona / Iruña'),
  Ubicacion(42.0617, -1.6046, 'Tudela'),
  Ubicacion(42.6712, -2.0322, 'Estella-Lizarra'),
  Ubicacion(40.4168, -3.7038, 'Madrid (Puerta del Sol)'),
  Ubicacion(40.4637, -3.6909, 'Madrid (Chamartín)'),
  Ubicacion(41.6488, -0.8891, 'Zaragoza (solo el día en curso)'),
];

class ErrorUbicacion implements Exception {
  final String mensaje;
  const ErrorUbicacion(this.mensaje);
  @override
  String toString() => mensaje;
}

Future<Ubicacion> ubicacionGps() async {
  if (!await Geolocator.isLocationServiceEnabled()) {
    throw const ErrorUbicacion('La ubicación del teléfono está desactivada.');
  }
  var permiso = await Geolocator.checkPermission();
  if (permiso == LocationPermission.denied) {
    permiso = await Geolocator.requestPermission();
  }
  if (permiso == LocationPermission.denied || permiso == LocationPermission.deniedForever) {
    throw const ErrorUbicacion('Sin permiso de ubicación. Puedes elegir un lugar a mano.');
  }
  final pos = await Geolocator.getCurrentPosition(
    locationSettings: const LocationSettings(accuracy: LocationAccuracy.high, timeLimit: Duration(seconds: 20)),
  );
  return Ubicacion(pos.latitude, pos.longitude, 'Tu ubicación', esGps: true);
}

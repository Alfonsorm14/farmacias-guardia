/// Preferencias guardadas solo en el teléfono.
library;

import 'package:shared_preferences/shared_preferences.dart';

import '../location.dart';

const _clave = 'ultimo_lugar';

/// Guarda el último lugar elegido a mano (nunca la posición GPS).
Future<void> guardarUltimoLugar(Ubicacion u) async {
  if (u.esGps) return;
  try {
    final p = await SharedPreferences.getInstance();
    await p.setStringList(_clave, [u.lat.toString(), u.lon.toString(), u.etiqueta]);
  } catch (_) {
    // Sin almacenamiento disponible: no es imprescindible.
  }
}

/// Último lugar elegido a mano, si lo hay.
Future<Ubicacion?> leerUltimoLugar() async {
  try {
    final p = await SharedPreferences.getInstance();
    final v = p.getStringList(_clave);
    if (v == null || v.length != 3) return null;
    final lat = double.tryParse(v[0]), lon = double.tryParse(v[1]);
    if (lat == null || lon == null) return null;
    return Ubicacion(lat, lon, v[2]);
  } catch (_) {
    return null;
  }
}

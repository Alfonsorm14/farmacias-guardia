/// Compartir texto con el selector del sistema (canal propio en MainActivity.kt, sin dependencias).
library;

import 'package:flutter/services.dart';

const MethodChannel canalCompartir = MethodChannel('es.alfonsorivero.farmacias_guardia/compartir');

/// Abre el selector de Android para compartir [texto]. Devuelve false si no se pudo
/// (plataforma sin canal, p. ej. tests o iOS por ahora): entonces conviene copiar al portapapeles.
Future<bool> compartirTexto(String texto) async {
  try {
    return await canalCompartir.invokeMethod<bool>('texto', {'texto': texto}) ?? false;
  } on MissingPluginException {
    return false;
  } on PlatformException {
    return false;
  }
}

/// Fechas y horas en la zona de España peninsular (Europe/Madrid), sea cual sea
/// la zona configurada en el teléfono.
library;

import 'package:timezone/data/latest_10y.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

bool _iniciado = false;

tz.Location get zonaMadrid {
  if (!_iniciado) {
    tzdata.initializeTimeZones();
    _iniciado = true;
  }
  return tz.getLocation('Europe/Madrid');
}

/// El instante [d] expresado en hora de Madrid.
tz.TZDateTime enMadrid(DateTime d) => tz.TZDateTime.from(d, zonaMadrid);

/// Medianoche (hora de Madrid) del día natural de Madrid [anio]-[mes]-[dia].
tz.TZDateTime inicioDiaMadrid(int anio, int mes, int dia) => tz.TZDateTime(zonaMadrid, anio, mes, dia);

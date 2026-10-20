"""Asignaciones explícitas de Murcia 2026 que no están en tabla (activadas el 20/10/2026).

El Anexo III del BORM nº 301 (31/12/2025) asigna algunos turnos en texto, no en cuadrante:
farmacias de urgencia permanente (Albudeite, Pliego, Almendricos, Aledo, Benizar), domingos y
festivos (Isla Plana, La Azohía, Calabardina) y listas de fechas (Ifre-Cañada de Gallego,
Camposol). Son asignaciones explícitas, no deducciones; Alfonso decidió incorporarlas el 20/10/2026
(docs/DECISION_murcia_rotaciones.md). Las "urgencias diurnas" sin horario publicado se cargan como día
completo con horario no exacto, y la app y la API no las muestran en "Ahora" (solo en las vistas de día).

Cada asignación lleva la cita literal del boletín (`cita`): los tests comprueban que aparece en
el PDF, para que un error de transcripción no pase inadvertido.

Festivos 2026 (los de domingos y festivos): Resolución de la Dirección General de Trabajo de
7/7/2025, BORM nº 163 de 17/07/2025 (NPE A-170725-3546): fiestas regionales y nacionales y
fiestas locales por municipio.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ingesta.model import DutyShift

TZ = ZoneInfo("Europe/Madrid")
YEAR = 2026

# BORM nº 163, 17/07/2025: fiestas laborales de 2026 en la Región de Murcia.
FESTIVOS_REGION_2026: frozenset[date] = frozenset({
    date(2026, 1, 1), date(2026, 1, 6), date(2026, 3, 19), date(2026, 4, 2), date(2026, 4, 3),
    date(2026, 5, 1), date(2026, 6, 9), date(2026, 8, 15), date(2026, 10, 12), date(2026, 12, 7),
    date(2026, 12, 8), date(2026, 12, 25),
})
# Misma resolución: fiestas locales.
FESTIVOS_LOCALES_2026: dict[str, frozenset[date]] = {
    "CARTAGENA": frozenset({date(2026, 3, 27), date(2026, 9, 25)}),
    "AGUILAS": frozenset({date(2026, 2, 17), date(2026, 3, 27)}),
}
# Transcripción de las filas usadas, con la referencia del boletín (los tests la contrastan).
FESTIVOS_FUENTE = "data/raw/murcia/2026/fiestas_laborales_2026.txt"


def festivos(municipio: str) -> frozenset[date]:
    return FESTIVOS_REGION_2026 | FESTIVOS_LOCALES_2026[municipio]


def _dias(cond) -> list[date]:
    d0 = date(YEAR, 1, 1)
    return [d0 + timedelta(days=i) for i in range(365) if cond(d0 + timedelta(days=i))]


@dataclass(frozen=True)
class Asignacion:
    pharmacy_id: str
    zone: str
    kind: str  # "diurna" | "localizada" | "refuerzo"
    dias: tuple[date, ...]
    cita: str  # texto literal del BORM (espacios normalizados)
    horas: tuple[time, time] | None = None  # None = el boletín no publica el horario

    def duty_shifts(self) -> list[DutyShift]:
        """Los mismos turnos como objetos del modelo común (para el parser)."""
        return [
            DutyShift(
                pharmacy_id=d["pharmacy_id"],
                zone=d["zone"],
                start=datetime.fromisoformat(d["start"]),
                end=datetime.fromisoformat(d["end"]),
                kind=d["kind"],
                raw_label=d["raw_label"],
                times_exact=d["times_exact"],
            )
            for d in self.shifts()
        ]

    def shifts(self) -> list[dict]:
        out = []
        for d in self.dias:
            if self.horas:
                ini = datetime.combine(d, self.horas[0], TZ)
                fin = datetime.combine(d, self.horas[1], TZ)
            else:
                ini = datetime.combine(d, time(0), TZ)
                fin = datetime.combine(d + timedelta(days=1), time(0), TZ)
            out.append({
                "pharmacy_id": self.pharmacy_id,
                "zone": self.zone,
                "start": ini.isoformat(),
                "end": fin.isoformat(),
                "kind": self.kind,
                "raw_label": f"{self.zone} — asignación en texto del Anexo III",
                "times_exact": self.horas is not None,
            })
        return out


def _ifre() -> tuple[date, ...]:
    lista = ("3-1, 17-1, 31-1, 14-2, 28-2, 14-3, 28-3, 4-4, 18-4, 2-5, 16-5, 30-5, 9-6, 20-6, 4-7, "
             "18-7, 1-8, 29-8, 12-9, 26-9, 12-10, 24-10, 7-11, 21-11, 7-12, 19-12")
    return tuple(date(YEAR, int(m), int(d)) for d, m in (x.strip().split("-") for x in lista.split(",")))


def asignaciones() -> list[Asignacion]:
    todos = tuple(_dias(lambda d: True))
    fc = festivos("CARTAGENA")
    fa = festivos("AGUILAS")
    return [
        # Agrupación 5 (Mula): única farmacia de cada localidad.
        Asignacion("MU:383", "AGRUPACION 5 (MULA) - Albudeite", "diurna", todos,
                   "Albudeite: urgencia diurna permanente localizada"),
        Asignacion("MU:146", "AGRUPACION 5 (MULA) - Pliego", "diurna", todos,
                   "Pliego: urgencia diurna permanente localizada"),
        # Agrupación 25 (Puerto Lumbreras).
        Asignacion("MU:198", "AGRUPACION 25 (PUERTO LUMBRERAS) - Almendricos", "localizada", todos,
                   "Almendricos: Turno de urgencia permanente localizado fuera del horario mínimo"),
        # Agrupación 26 (Totana).
        Asignacion("MU:422", "AGRUPACION 26 (TOTANA) - Aledo", "localizada", todos,
                   "Aledo: farmacia en servicio permanente de urgencia, en sistema localizado fuera del horario mínimo"),
        # Agrupación 32 (Moratalla).
        Asignacion("MU:424", "AGRUPACION 32 (MORATALLA) - Benizar", "diurna", todos,
                   "Pedanía de Benizar: servicio de urgencia diurno permanente"),
        # Agrupación 18 (Mazarrón y pedanías de Cartagena).
        Asignacion("MU:433", "AGRUPACION 18 (MAZARRON) - Isla Plana", "diurna",
                   tuple(_dias(lambda d: (d.weekday() == 6 or d in fc)
                               and d not in {date(YEAR, 1, 1), date(YEAR, 12, 25)})),
                   "Turno de urgencia diurna localizada, todos los domingos y festivos del año 2026, "
                   "excepto 1 de enero y 25 de diciembre (MU-433-F"),
        Asignacion("MU:498", "AGRUPACION 18 (MAZARRON) - La Azohía", "diurna",
                   tuple(_dias(lambda d: (
                       ((d.weekday() == 5 or (d in fc and d.weekday() != 6))
                        and d not in {date(YEAR, 1, 1), date(YEAR, 1, 6), date(YEAR, 11, 1), date(YEAR, 12, 25)})
                       or (d.weekday() == 6 and date(YEAR, 7, 1) <= d <= date(YEAR, 9, 11))
                   ))),
                   "Turno de urgencia diurna localizada todos los sábados y festivos (no domingos) del año "
                   "2026, excepto el 1-1, 6-1, 1-11 y 25-12; y turno de urgencia diurna localizada los "
                   "domingos de julio, agosto, y hasta el 11 de septiembre (MU-498-F"),
        Asignacion("MU:493", "AGRUPACION 18 (MAZARRON) - Ifre-Cañada Gallego", "diurna", _ifre(),
                   "Turno de urgencia diurna localizada los siguientes días: 3-1, 17-1, 31-1"),
        Asignacion("MU:584", "AGRUPACION 18 (MAZARRON) - Camposol", "diurna", (date(YEAR, 7, 15),),
                   "Turno de urgencia diurna localizada: 15-7 (MU-584-F"),
        # Agrupación 22 (Águilas): refuerzo con horario publicado.
        Asignacion("MU:452", "AGRUPACION 22 (AGUILAS SUR/NORTE) - Calabardina", "refuerzo",
                   tuple(_dias(lambda d: d.month in (7, 8) and (d.weekday() == 6 or d in fa))),
                   "MU-452-F, Jesús Fernández Rabal: Refuerzo de 10 a 21 horas, los domingos y festivos "
                   "de los meses de julio y agosto",
                   horas=(time(10), time(21))),
    ]

"""Análisis (NO activado, decisión 20/10/2026: no deducir): turnos de Murcia según las reglas de rotación del BORM.

Genera data/propuestas/murcia_rotaciones_2026.json (mismo formato que data/out; ignorado por git)
e imprime la tabla por agrupación y una prueba retrospectiva: en las agrupaciones con cuadrante
anual publicado, se aplica el mismo método a enero y se compara con lo publicado de febrero a
diciembre. No toca data/out ni la base de datos (decisión pendiente: docs/DECISION_murcia_rotaciones.md).

Uso:
    python scripts/proyectar_rotaciones_murcia.py
"""
from __future__ import annotations

import collections
import json
import os
import sys
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from ingesta.common import pdf_to_text  # noqa: E402
from ingesta.parsers.murcia_rotacion import (  # noqa: E402
    TZ,
    evaluate_zone,
    project_zone,
    rule_texts,
    split_annexes,
    vacations,
)

PDF = os.path.join(BASE_DIR, "data", "raw", "murcia", "2026", "BORM_2025_6468.pdf")
SRC = os.path.join(BASE_DIR, "data", "out", "murcia_2026.json")
PROP = os.path.join(BASE_DIR, "data", "propuestas")
OUT = os.path.join(PROP, "murcia_rotaciones_2026.json")


def backtest(by_zone: dict[str, list[dict]], reglas: dict[int, str], vac: dict) -> list[str]:
    """Aplica el método a enero de las zonas con cuadrante anual y compara con lo publicado."""
    def dia(s: dict) -> date:
        return datetime.fromisoformat(s["start"]).astimezone(TZ).date()

    out = []
    for zone, ss in sorted(by_zone.items()):
        if max(dia(s) for s in ss) < date(2026, 3, 1):
            continue
        jan = [s for s in ss if dia(s) < date(2026, 2, 1)]
        if not jan:
            continue
        ev = evaluate_zone(zone, jan, {s["pharmacy_id"] for s in jan}, reglas, vac)
        if ev is None or not ev.proyectable:
            out.append(f"{zone}: no aplicable ({ev.motivo if ev else 'sin enero'})")
            continue
        real: dict[date, set] = collections.defaultdict(set)
        pred: dict[date, set] = collections.defaultdict(set)
        for s in ss:
            if dia(s) >= date(2026, 2, 1):
                real[dia(s)].add(s["pharmacy_id"])
        for s in project_zone(ev, jan, set()):
            pred[dia(s)].add(s["pharmacy_id"])
        dias = sorted(set(real) | set(pred))
        fallos = [d for d in dias if real[d] != pred[d]]
        out.append(
            f"{zone}: {len(dias) - len(fallos)}/{len(dias)} días iguales; distintos: "
            + ", ".join(d.strftime("%d/%m") for d in fallos)
        )
    return out


def backtest_baleares() -> list[str]:
    """Baleares publica el año entero: ¿cuánto acierta repetir el ciclo que se ve en enero?"""
    with open(os.path.join(BASE_DIR, "data", "out", "baleares_2026.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    zonas: dict[str, dict[date, set]] = collections.defaultdict(lambda: collections.defaultdict(set))
    for s in data["shifts"]:
        d = datetime.fromisoformat(s["start"]).astimezone(TZ).date()
        zonas[s["zone"]][d].add((s["pharmacy_id"], s["kind"]))
    out, total_ok, total = [], 0, 0
    for zona, dias in sorted(zonas.items()):
        enero = sorted(d for d in dias if d < date(2026, 2, 1))
        seq = [frozenset(dias[d]) for d in enero]
        n = len(seq)
        periodo = next((p for p in range(1, n) if all(seq[i] == seq[i + p] for i in range(n - p))), None)
        if periodo is None or n - periodo < min(periodo, 7):
            continue
        resto = [d for d in sorted(dias) if d >= date(2026, 2, 1)]
        ok = sum(1 for d in resto if dias[d] == frozenset(dias[enero[0] + timedelta(days=(d - enero[0]).days % periodo)]))
        total_ok += ok
        total += len(resto)
        out.append(f"{zona}: ciclo de {periodo} días; {ok}/{len(resto)} días iguales ({100 * ok / len(resto):.0f} %)")
    out.append(f"Zonas con ciclo visible en enero: {len(out)} de {len(zonas)}; total {total_ok}/{total} días iguales")
    return out


def main() -> int:
    text = pdf_to_text(PDF)
    anexo_i, anexo_iii = split_annexes(text)
    reglas = rule_texts(anexo_iii)
    vac, avisos = vacations(anexo_i)
    with open(SRC, encoding="utf-8") as fh:
        data = json.load(fh)
    by_zone: dict[str, list[dict]] = collections.defaultdict(list)
    for s in data["shifts"]:
        by_zone[s["zone"]].append(s)
    zone_pharm: dict[str, set[str]] = collections.defaultdict(set)
    for p in data["pharmacies"]:
        for z in p["zones"]:
            zone_pharm[z].add(p["id"])
    localities = {p["id"]: p["locality"] for p in data["pharmacies"]}

    evaluaciones = []
    proyectados: list[dict] = []
    for zone in sorted(by_zone):
        if "Cambios" in zone:
            continue
        ev = evaluate_zone(zone, by_zone[zone], zone_pharm[zone], reglas, vac)
        if ev is None:
            continue
        evaluaciones.append(ev)
        if not ev.proyectable:
            continue
        explicit = {
            datetime.fromisoformat(s["start"]).astimezone(TZ).date()
            for z, ss in by_zone.items()
            if z != zone and "Cambios" in z and z.startswith(zone.split(" - ")[0])
            for s in ss
        }
        proyectados.extend(project_zone(ev, by_zone[zone], explicit))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out = {
        "source": data["source"],
        "pharmacies": data["pharmacies"],
        "shifts": data["shifts"] + proyectados,
        "warnings": data.get("warnings", []) + [f"PROPUESTA: {len(proyectados)} turnos deducidos"],
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    hoy = date(2026, 10, 20)
    print(f"Zonas con solo enero publicado: {len(evaluaciones)}")
    print(f"Proyectables: {sum(e.proyectable for e in evaluaciones)}  turnos deducidos: {len(proyectados)}")
    for e in evaluaciones:
        locs = sorted({(localities.get(p) or '?') for p in zone_pharm[e.zona]})
        estado = f"SÍ ({e.tipo}, ciclo {e.periodo} días)" if e.proyectable else f"NO: {e.motivo}"
        dias_vac = sum(len(v) for v in e.vacaciones.values())
        print(f"| {e.zona} | {e.farmacias} | {', '.join(locs)[:60]} | {estado} | {dias_vac} |")
    print("\nPrueba retrospectiva (agrupaciones con cuadrante anual publicado):")
    for linea in backtest(by_zone, reglas, vac):
        print(" ", linea)
    print("\nPrueba retrospectiva en Baleares (solo periodicidad de enero, sin reglas escritas):")
    for linea in backtest_baleares():
        print(" ", linea)
    if avisos:
        print("\nAvisos de vacaciones:")
        for a in avisos:
            print(" -", a)
    del hoy
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

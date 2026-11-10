"""Genera planillas mineras FICTICIAS para practicar, con errores puestos a propósito.

Uso: python -B scripts/datos_mineros.py [--output examples/minera2] [--seed 2026]
La carpeta de salida no debe existir. `respuestas.json` lista los errores inyectados.
"""
import argparse
import csv
import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kitlib.runtime import configure, inside

configure()
p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
p.add_argument("--output", type=Path, default=ROOT / "examples" / "minera")
p.add_argument("--seed", type=int, default=2026)
args = p.parse_args()
out = inside(args.output)
out.mkdir(parents=True, exist_ok=False)
rng = random.Random(args.seed)
START = date(2026, 10, 1)
DAYS = [START + timedelta(days=i) for i in range(31)]


def write(name, columns, rows, encoding="utf-8"):
    path = out / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding=encoding, newline="") as stream:
        writer = csv.writer(stream, delimiter=";", lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)


def dec(value):
    return f"{value:.1f}".replace(".", ",")


# Flota: códigos con ceros a la izquierda que Excel suele estropear.
kinds = [("CAEX", "Camión de extracción 300 t", "Mina", 24), ("PALA", "Pala eléctrica", "Mina", 5),
         ("PERF", "Perforadora", "Mina", 5), ("CARG", "Cargador frontal", "Mina", 4),
         ("CHAN", "Chancador", "Planta", 2), ("CORR", "Correa transportadora", "Planta", 4)]
fleet = []
for prefix, model, area, count in kinds:
    for n in range(1, count + 1):
        state = rng.choices(["operativo", "en mantención", "fuera de servicio"], [84, 12, 4])[0]
        fleet.append([f"{prefix}-{n:03d}", model.split()[0].lower(), model, area, str(rng.randint(2012, 2025)), state])
FLEET_COLUMNS = ["equipo", "tipo", "modelo", "area", "año", "estado"]
write("flota.csv", FLEET_COLUMNS, fleet)
write("flota_excel_windows.csv", FLEET_COLUMNS, fleet, encoding="cp1252")
codes = [row[0] for row in fleet]
trucks = [c for c in codes if c.startswith("CAEX")]

# Versión anterior de la flota, para practicar comparar.
previous = [row.copy() for row in fleet]
changed = rng.sample(range(len(previous) - 2), 6)  # no tocar los dos que se quitan
for index in changed:
    previous[index][5] = "en mantención" if previous[index][5] == "operativo" else "operativo"
added = [previous.pop(), previous.pop()]  # existen ahora, no antes
removed = ["CAEX-099", "camión", "Camión de extracción 300 t", "Mina", "2009", "fuera de servicio"]
previous.insert(10, removed)
write("flota_anterior.csv", FLEET_COLUMNS, previous)

# Órdenes de mantención.
ORDER_COLUMNS = ["orden", "equipo", "tipo", "prioridad", "fecha_apertura", "fecha_cierre", "horas", "estado", "tecnico", "descripcion"]
tasks = ["Cambio de filtros", "Revisión de frenos", "Fuga hidráulica", "Cambio de neumático", "Falla eléctrica",
         "Lubricación general", "Inspección estructural", "Cambio de correa", "Calibración de sensores", "Reparación de motor"]
orders = []
for n in range(1, 601):
    opened = rng.choice(DAYS)
    state = rng.choices(["cerrada", "abierta", "en proceso"], [70, 18, 12])[0]
    closed = (opened + timedelta(days=rng.randint(0, 6))).isoformat() if state == "cerrada" else ""
    orders.append([f"OT-{n:06d}", rng.choice(codes), rng.choices(["preventiva", "correctiva", "inspección"], [45, 40, 15])[0],
                   rng.choices(["alta", "media", "baja"], [20, 50, 30])[0], opened.isoformat(), closed,
                   dec(rng.uniform(0.5, 16)), state, f"T-{rng.randint(1, 18):02d}", rng.choice(tasks)])
picks = rng.sample(range(len(orders)), 30)
answers = {"orden_duplicada": 5, "equipo_vacio": 4, "equipo_inexistente": 3, "fecha_formato_dia_mes_año": 6,
           "horas_negativas": 3, "horas_sobre_72": 3, "estado_mal_escrito": 4, "horas_vacias": 2}
it = iter(picks)
for _ in range(5):
    i = next(it)
    orders[i][0] = orders[(i + 7) % len(orders)][0]
for _ in range(4):
    orders[next(it)][1] = ""
for _ in range(3):
    orders[next(it)][1] = f"CAEX-{rng.randint(200, 299)}"
for _ in range(6):
    i = next(it)
    orders[i][4] = date.fromisoformat(orders[i][4]).strftime("%d/%m/%Y")
for _ in range(3):
    orders[next(it)][6] = dec(-rng.uniform(1, 8))
for _ in range(3):
    orders[next(it)][6] = dec(rng.uniform(100, 900))
for wrong in ("cerada", "Cerrada", "abierto", "CERRADA"):
    orders[next(it)][7] = wrong
for _ in range(2):
    orders[next(it)][6] = ""
write("ordenes.csv", ORDER_COLUMNS, orders)

# Detenciones de equipos.
causes = ["falla mecánica", "falla eléctrica", "neumáticos", "espera de repuesto", "clima", "operacional", "mantención programada"]
stops = []
for _ in range(450):
    start = datetime.combine(rng.choice(DAYS), datetime.min.time()) + timedelta(minutes=rng.randrange(0, 1440, 15))
    hours = round(rng.choices([rng.uniform(0.25, 4), rng.uniform(4, 30)], [80, 20])[0], 1)
    stops.append([rng.choice(codes), start.strftime("%Y-%m-%d %H:%M"), (start + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M"),
                  dec(hours), rng.choices(causes, [22, 14, 10, 12, 6, 16, 20])[0], "A" if 8 <= start.hour < 20 else "B"])
stops.sort(key=lambda row: row[1])
write("detenciones.csv", ["equipo", "inicio", "fin", "horas", "causa", "turno"], stops)

# Producción por turno: dos archivos compatibles para consolidar.
for shift in ("A", "B"):
    production = []
    for day in DAYS:
        for truck in trucks:
            if rng.random() < 0.85:
                trips = rng.randint(8, 22)
                production.append([day.isoformat(), truck, shift, str(trips), dec(trips * rng.uniform(270, 305))])
    write(f"produccion/turno_{shift}.csv", ["fecha", "equipo", "turno", "viajes", "toneladas"], production)

# Combustible, con algunos litros vacíos o negativos.
fuel = []
for day in DAYS:
    for truck in trucks:
        fuel.append([day.isoformat(), truck, str(rng.randint(2800, 4600))])
bad_fuel = rng.sample(range(len(fuel)), 9)
for i in bad_fuel[:5]:
    fuel[i][2] = ""
for i in bad_fuel[5:]:
    fuel[i][2] = str(-rng.randint(100, 900))
answers.update(litros_vacios=5, litros_negativos=4)
write("combustible.csv", ["fecha", "equipo", "litros"], fuel)

states = ["abierta", "cerrada", "en proceso"]
rules = {"columns": {
    "orden": {"required": True, "nonempty": True, "unique": True},
    "equipo": {"required": True, "nonempty": True},
    "tipo": {"required": True, "allowed": ["preventiva", "correctiva", "inspección"]},
    "prioridad": {"required": True, "allowed": ["alta", "media", "baja"]},
    "fecha_apertura": {"required": True, "nonempty": True, "type": "date"},
    "fecha_cierre": {"type": "date"},
    "horas": {"required": True, "nonempty": True, "type": "number", "decimal": ",", "min": "0", "max": "72"},
    "estado": {"required": True, "nonempty": True, "allowed": states}}}
plan = {"steps": [
    {"op": "filter", "column": "estado", "operator": "eq", "value": "cerrada"},
    {"op": "group", "by": ["equipo"], "decimal": ",", "aggregates": [
        {"op": "count", "as": "ordenes"}, {"op": "sum", "column": "horas", "as": "horas_totales"}]},
    {"op": "sort", "columns": ["horas_totales"], "type": "number", "descending": True}]}
fuel_rules = {"columns": {"fecha": {"required": True, "type": "date"}, "equipo": {"required": True, "nonempty": True},
                          "litros": {"required": True, "nonempty": True, "type": "integer", "min": "0"}}}
for name, content in (("reglas_ordenes.json", rules), ("plan_horas_por_equipo.json", plan),
                      ("reglas_combustible.json", fuel_rules),
                      ("respuestas.json", {"semilla": args.seed, "errores_inyectados": answers,
                                           "flota_vs_anterior": {"nuevos": 2, "eliminados": 1, "modificados": 6}})):
    with (out / name).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(content, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
print(f"Datos ficticios creados en {out}: {len(fleet)} equipos, {len(orders)} órdenes, {len(stops)} detenciones.")

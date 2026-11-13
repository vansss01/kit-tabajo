"""Mediciones reproducibles de tiempo, tamaño de salidas y memoria con un conjunto ficticio de tamaño moderado.

Uso: python -B scripts/medir.py [--filas 100000] [--repeticiones 3] [--semilla 2026] [--salida tmp/medicion]

1. Genera (con semilla fija) órdenes ficticias con las columnas de examples/reglas.json: ``orden;equipo;fecha;
   horas;estado``, repartidas en 4 archivos de turno, y una versión «anterior» con cambios; nada se commitea.
2. Ejecuta cada comando ``--repeticiones`` veces en una carpeta de salida propia y mide: tiempo de pared
   (mediana, mínimo, máximo), tamaño total de la carpeta de resultados y memoria máxima del proceso (ru_maxrss;
   en Windows no está disponible y se informa como null).
3. Deja ``medicion.json`` y ``medicion.md`` en la carpeta de salida y muestra la tabla en la terminal.

Las cifras valen para el equipo, el sistema y el tamaño medidos; no son una garantía general.
"""
import argparse
import csv
import json
import platform
import random
import statistics
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kitlib import __version__
from kitlib.runtime import configure, inside

configure()
# Mide ru_maxrss del único hijo que lanza, para que la cifra sea de ese comando y no del acumulado del proceso.
WRAPPER = ("import resource, subprocess, sys\n"
           "code = subprocess.run(sys.argv[1:]).returncode\n"
           "print('RU_MAXRSS', resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)\n"
           "sys.exit(code)\n")


def generar(folder, rows, seed):
    rng = random.Random(seed)
    equipos = [f"{n:04d}" for n in range(1, 61)]
    estados = ["abierta", "abierta", "abierta", "cerrada"]
    start = date(2026, 10, 1)
    folder.mkdir(parents=True)
    turnos = folder / "turnos"
    turnos.mkdir()
    writers = []
    for i in range(4):
        stream = (turnos / f"turno_{i + 1}.csv").open("x", encoding="utf-8", newline="")
        writer = csv.writer(stream, delimiter=";", lineterminator="\n")
        writer.writerow(["orden", "equipo", "fecha", "horas", "estado"])
        writers.append((stream, writer))
    completo = (folder / "ordenes.csv").open("x", encoding="utf-8", newline="")
    todo = csv.writer(completo, delimiter=";", lineterminator="\n")
    todo.writerow(["orden", "equipo", "fecha", "horas", "estado"])
    anterior = (folder / "anterior.csv").open("x", encoding="utf-8", newline="")
    antes = csv.writer(anterior, delimiter=";", lineterminator="\n")
    antes.writerow(["orden", "equipo", "fecha", "horas", "estado"])
    for n in range(1, rows + 1):
        row = [f"OT{n:07d}", rng.choice(equipos), (start + timedelta(days=rng.randrange(31))).isoformat(),
               f"{rng.randrange(0, 240) / 10:.1f}".replace(".", ","), rng.choice(estados)]
        if n % 1000 == 0:  # 1 de cada 1000: horas fuera de rango (incidencia real para validar)
            row[3] = "25,0"
        todo.writerow(row)
        writers[n % 4][1].writerow(row)
        if n % 50 != 0:  # anterior: faltan 2 % de las filas y 1 % cambia de horas
            antes.writerow(row if n % 100 else [*row[:3], "1,0", row[4]])
    for stream, _ in writers:
        stream.close()
    completo.close()
    anterior.close()


def tamano(folder):
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


def medir(nombre, args, out, reps, expected):
    tiempos: list[float] = []
    memorias: list[float] = []
    tamanos: list[int] = []
    for i in range(reps):
        run = f"{nombre}-{i + 1}"
        command = [sys.executable, "-B", str(ROOT / "kit.py"), *args, "--output", str(out), "--run-name", run, "--json"]
        if sys.platform != "win32":
            command = [sys.executable, "-c", WRAPPER, *command]
        start = time.perf_counter()
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, encoding="utf-8")
        tiempos.append(time.perf_counter() - start)
        if result.returncode != expected:
            raise SystemExit(f"{nombre}: código {result.returncode}, se esperaba {expected}\n{result.stdout[-800:]}"
                             f"{result.stderr[-800:]}")
        mem = [line.split()[1] for line in result.stdout.splitlines() if line.startswith("RU_MAXRSS")]
        if mem:
            memorias.append(int(mem[0]) / 1024)  # ru_maxrss en KiB en Linux → MiB
        tamanos.append(tamano(out / run))
    return {"comando": nombre, "argumentos": " ".join(a for a in args if not a.startswith("/")),
            "repeticiones": reps, "codigo_salida": expected,
            "segundos": {"mediana": round(statistics.median(tiempos), 2), "min": round(min(tiempos), 2),
                         "max": round(max(tiempos), 2)},
            "memoria_max_mib": round(max(memorias)) if memorias else None,
            "tamano_salida_kib": round(tamanos[0] / 1024)}


def main():
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("--filas", type=int, default=100_000)
    p.add_argument("--repeticiones", type=int, default=3)
    p.add_argument("--semilla", type=int, default=2026)
    p.add_argument("--salida", type=Path, default=ROOT / "tmp" / "medicion")
    a = p.parse_args()
    base = inside(a.salida)
    if base.exists():
        raise SystemExit(f"La carpeta {base} ya existe; use otra --salida (nunca se sobrescribe)")
    datos, out = base / "datos", base / "resultados"
    generar(datos, a.filas, a.semilla)
    out.mkdir()
    sep = ["--delimiter", ";", "--decimal", ","]
    ordenes, anterior, turnos = str(datos / "ordenes.csv"), str(datos / "anterior.csv"), str(datos / "turnos")
    reglas, plan, receta = str(ROOT / "examples" / "reglas.json"), str(ROOT / "examples" / "plan.json"), \
        str(ROOT / "recetas" / "revision_ordenes.json")
    casos = [
        ("inspeccionar", ["inspeccionar", ordenes, *sep], 0),
        ("validar", ["validar", ordenes, *sep, "--rules", reglas], 1),
        ("comparar", ["comparar", anterior, ordenes, *sep, "--key", "orden"], 0),
        ("consolidar", ["consolidar", turnos, *sep], 0),
        ("transformar", ["transformar", ordenes, *sep, "--plan", plan], 0),
        ("consultar", ["consultar", ordenes, *sep, "--tipo", "t.horas=number", "--show", "0",
                       "--sql", "SELECT equipo, COUNT(*) AS n, SUM(horas) AS horas FROM t GROUP BY equipo"], 0),
        ("exportar_csv", ["exportar", ordenes, *sep, "--format", "csv"], 0),
        ("exportar_xlsx", ["exportar", ordenes, *sep, "--format", "xlsx"], 0),
        ("ejecutar", ["ejecutar", ordenes, "--receta", receta], 1),
    ]
    resultados = [medir(nombre, args, out, a.repeticiones, code) for nombre, args, code in casos]
    entorno = {"fecha_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "version_kit": __version__,
               "python": platform.python_version(), "sistema": platform.platform(), "maquina": platform.machine(),
               "filas": a.filas, "columnas": 5, "archivos_turno": 4, "semilla": a.semilla,
               "tamano_entrada_kib": round((datos / "ordenes.csv").stat().st_size / 1024), "repeticiones": a.repeticiones,
               "nota": "Cifras de este equipo y tamaño; no son una garantía general."}
    (base / "medicion.json").write_text(json.dumps({"entorno": entorno, "mediciones": resultados}, ensure_ascii=False,
                                                   indent=1), encoding="utf-8")
    lines = [f"Entrada: {a.filas} filas × 5 columnas ({entorno['tamano_entrada_kib']} KiB), semilla {a.semilla}, "
             f"{a.repeticiones} repeticiones, Python {entorno['python']}, {entorno['sistema']}", "",
             "| Comando | Código | Segundos (mediana / mín / máx) | Memoria máx. (MiB) | Salida (KiB) |",
             "|---|---|---|---|---|"]
    for r in resultados:
        s = r["segundos"]
        lines.append(f"| {r['comando']} | {r['codigo_salida']} | {s['mediana']} / {s['min']} / {s['max']} | "
                     f"{'n/d' if r['memoria_max_mib'] is None else r['memoria_max_mib']} | {r['tamano_salida_kib']} |")
    (base / "medicion.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nDetalle: {base / 'medicion.json'}")


if __name__ == "__main__":
    main()

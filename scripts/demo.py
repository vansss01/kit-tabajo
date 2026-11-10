"""Demostración comprobada con datos ficticios. No sobrescribe ejecuciones previas."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kitlib.runtime import configure
from kitlib.tableio import json_write

configure()
examples = ROOT / "examples"
originals = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in examples.rglob("*") if p.is_file()}
runs: list[dict] = []


def run(command, input_path, *extra, expected=0):
    command_line = [sys.executable, "-B", str(ROOT / "kit.py"), command, str(input_path),
                    "--delimiter", ";", "--decimal", ",", "--json", *map(str, extra)]
    result = subprocess.run(command_line, cwd=ROOT, text=True, capture_output=True)
    if result.returncode != expected:
        raise RuntimeError(f"{command}: código {result.returncode}; {result.stdout[:1000]} {result.stderr[:1000]}")
    summary = json.loads(result.stdout)
    runs.append(summary)
    print(f"{command}: {summary['estado']} ({summary['filas_procesadas']} filas)")
    return Path(summary["ruta_resultados"])


run("inspeccionar", examples / "equipos.csv")
run("inspeccionar", examples / "entradas" / "turno A.csv")
validation = run("validar", examples / "con incidencias.csv", "--rules", examples / "reglas.json", expected=1)
report = json.loads((validation / "report.json").read_text(encoding="utf-8"))
assert report["detalle"]["validas"] == 1 and report["detalle"]["invalidas"] == 2
consolidated = run("consolidar", examples / "entradas")
rows = json.loads((consolidated / "validos.json").read_text(encoding="utf-8"))["rows"]
assert len(rows) == 4 and rows[0]["equipo"] == "0007"
clean_plan = consolidated / "seleccion.json"
json_write(clean_plan, {"steps": [{"op": "select", "columns": ["orden", "equipo", "fecha", "horas", "estado"]}]})
selected = run("transformar", consolidated / "validos.json", "--plan", clean_plan)
comparison = run("comparar", examples / "anterior.csv", selected / "validos.json", "--key", "orden")
counts = json.loads((comparison / "report.json").read_text(encoding="utf-8"))["detalle"]
assert counts == {"nuevos": 2, "eliminados": 1, "modificados": 1, "sin_cambios": 1, "campos_cambiados": 1}
transformed = run("transformar", consolidated / "validos.json", "--plan", examples / "plan.json")
result_rows = json.loads((transformed / "validos.json").read_text(encoding="utf-8"))["rows"]
assert result_rows == [{"equipo": "0007", "ordenes": "2", "horas_totales": "5.5"},
                       {"equipo": "0042", "ordenes": "1", "horas_totales": "4.0"}]
run("exportar", transformed / "validos.json")
run("exportar", examples / "con incidencias.csv", "--rules", examples / "reglas.json", expected=1)
for path, digest in originals.items():
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
last = Path(runs[-1]["ruta_resultados"])
json_write(last / "demo_verificada.json", {"ejecuciones": runs, "originales_intactos": True,
           "comparacion": counts, "resumen_esperado": result_rows})
print("Flujo completo verificado. Registro:", last / "demo_verificada.json")

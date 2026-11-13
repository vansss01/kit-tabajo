"""Pendientes de etapas anteriores, por la CLI:

- Compatibilidad: un comando suelto y el mismo paso dentro de una receta producen las mismas filas y las
  mismas incidencias (validar, transformar, consolidar).
- Salidas compactas: el resumen `--json` de `ejecutar` no arrastra detalles, y `resultados` respeta sus
  topes (30 pasos, 40 archivos, 15 códigos, 100 incidencias, 200 caracteres por detalle) aunque la
  ejecución sea mayor.
- Privacidad: con `--ocultar-valores` ninguna celda de las recetas de ejemplo llega a la terminal ni a
  los resúmenes JSON (manifiesto y report.json).
Los valores esperados están escritos a mano a partir de examples/recetas/*.csv."""
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kitlib.runtime import configure

configure()
EJEMPLOS = ROOT / "examples" / "recetas"
NEGOCIO = ["orden", "equipo", "fecha", "horas", "estado"]


def kit(*args, expected=0, cwd=ROOT):
    result = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), *map(str, args)], cwd=cwd, text=True,
                            capture_output=True, encoding="utf-8")
    if expected is not None and result.returncode != expected:
        raise AssertionError(f"código {result.returncode}: {result.stdout[:800]} {result.stderr[:800]}")
    return result


def rows(path, columns=None):
    with path.open(encoding="utf-8", newline="") as stream:
        table = list(csv.reader(stream, delimiter=";"))
    if columns is None:
        return table
    index = [table[0].index(c) for c in columns]
    return [[r[i] for i in index] for r in table[1:]]


def issues(path):
    """(fila, columna, codigo) de un incidencias.csv, sin el origen (el suelto cita la ruta, la receta la entrada)."""
    return sorted((r[1], r[2], r[0]) for r in rows(path)[1:])


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="compat-", dir=ROOT / "tmp")
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.out = self.folder / "salidas"

    def run_recipe(self, recipe, principal, *extra, expected):
        result = kit("ejecutar", principal, "--receta", recipe, "--output", self.out, "--json", *extra, expected=expected)
        summary = json.loads(result.stdout)
        return summary, Path(summary["ruta_resultados"])

    def run_command(self, command, path, *extra, expected):
        result = kit(command, path, "--delimiter", ";", "--decimal", ",", "--output", self.out, "--json", *extra,
                     expected=expected)
        return Path(json.loads(result.stdout)["ruta_resultados"])


class CompatibilidadTests(Base):
    def test_validar_suelto_y_paso_de_receta_separan_las_mismas_filas(self):
        source = EJEMPLOS / "ordenes_semana_1.csv"
        loose = self.run_command("validar", source, "--rules", ROOT / "examples" / "reglas.json", expected=1)
        _, run = self.run_recipe(ROOT / "recetas" / "revision_ordenes.json", source, expected=1)
        step = run / "02-revision"
        self.assertEqual(rows(step / "aceptadas.csv"), rows(loose / "validos.csv"))
        self.assertEqual(rows(step / "rechazadas.csv"), rows(loose / "invalidos.csv"))
        self.assertEqual(issues(step / "incidencias.csv"), issues(loose / "incidencias.csv"))
        # A mano: 3 aceptadas (OT100, OT101, OT108) y 7 incidencias en 7 filas distintas.
        self.assertEqual([r[0] for r in rows(loose / "validos.csv")[1:]], ["OT100", "OT101", "OT108"])
        self.assertEqual(len(issues(loose / "incidencias.csv")), 7)

    def test_transformar_suelto_sobre_la_salida_de_un_paso_reproduce_el_paso_siguiente(self):
        _, run = self.run_recipe(ROOT / "recetas" / "revision_ordenes.json", EJEMPLOS / "ordenes_semana_1.csv",
                                 expected=1)
        loose = self.run_command("transformar", run / "02-revision" / "aceptadas.csv", "--plan",
                                 ROOT / "examples" / "plan.json", expected=0)
        self.assertEqual(rows(loose / "validos.csv"), rows(run / "03-resumen" / "resultado.csv"))
        self.assertEqual(rows(loose / "validos.csv"), [["equipo", "ordenes", "horas_totales"], ["0007", "2", "3.0"]])
        # rename suelto = paso adaptar de la receta de turnos.
        plan = self.folder / "renombrar.json"
        plan.write_text(json.dumps({"steps": [{"op": "rename", "columns": {
            "OT": "orden", "Equipo": "equipo", "Fecha": "fecha", "Hrs": "horas", "Estado": "estado"}}]}),
            encoding="utf-8")
        renamed = self.run_command("transformar", EJEMPLOS / "turno_b_exportado.csv", "--plan", plan, expected=0)
        _, turnos = self.run_recipe(ROOT / "recetas" / "consolidacion_turnos.json", EJEMPLOS / "turno_a.csv", expected=1)
        self.assertEqual(rows(renamed / "validos.csv"), rows(turnos / "01-adaptar" / "resultado.csv"))
        self.assertEqual(rows(renamed / "validos.csv")[0], NEGOCIO)

    def test_consolidar_suelto_y_paso_de_receta_unen_igual_con_la_misma_procedencia(self):
        entradas = ROOT / "examples" / "entradas"  # turno A.csv y turno B.csv, mismas columnas
        loose = self.run_command("consolidar", entradas, expected=0)
        recipe = self.folder / "union.json"
        recipe.write_text(json.dumps({
            "version": 1, "nombre": "union",
            "entradas": {"a": {"principal": True, "delimiter": ";", "decimal": ","},
                         "b": {"ruta": str(entradas / "turno B.csv"), "delimiter": ";", "decimal": ","}},
            "pasos": [{"nombre": "union", "op": "consolidar", "entradas": ["a", "b"]}]}), encoding="utf-8")
        _, run = self.run_recipe(recipe, entradas / "turno A.csv", expected=0)
        step = rows(run / "01-union" / "resultado.csv")
        merged = rows(loose / "validos.csv")
        self.assertEqual(step[0], merged[0])
        columns = NEGOCIO + ["__fila_origen"]
        self.assertEqual(rows(run / "01-union" / "resultado.csv", columns), rows(loose / "validos.csv", columns))
        # A mano: 2 + 2 filas; la procedencia cita el archivo real (fila 2 y 3 de cada turno).
        self.assertEqual(rows(loose / "validos.csv", ["orden", "__fila_origen"]),
                         [["OT001", "2"], ["OT002", "3"], ["OT003", "2"], ["OT004", "3"]])
        files = [Path(r[0]).name for r in rows(run / "01-union" / "resultado.csv", ["__archivo_origen"])]
        self.assertEqual(files, [Path(r[0]).name for r in rows(loose / "validos.csv", ["__archivo_origen"])])
        self.assertEqual(files, ["turno A.csv", "turno A.csv", "turno B.csv", "turno B.csv"])


class CompactoTests(Base):
    def test_ejecutar_json_summary_has_counts_not_details(self):
        summary, run = self.run_recipe(ROOT / "recetas" / "revision_ordenes.json", EJEMPLOS / "ordenes_semana_1.csv",
                                       expected=1)
        self.assertNotIn("incidencias_detalle", summary)
        self.assertNotIn("detalles", json.dumps(summary))
        self.assertEqual({k for p in summary["pasos"] for k in p} - {"nombre", "op", "estado", "incidencias",
                                                                      "advertencias", "filas", "excluidas", "carpeta"},
                         set())
        self.assertLess(len(json.dumps(summary, ensure_ascii=False)), 3000)
        self.assertLessEqual(len(summary["incidencias_por_codigo"]), 15)
        # El detalle completo sigue en los archivos, no en la terminal.
        self.assertTrue((run / "02-revision" / "report.json").is_file())

    def fake_run(self, steps=35, codes=20, files=45, detail=300):
        """Ejecución fabricada a mano con más pasos, códigos, archivos y texto que los topes de `resultados`."""
        run = self.out / "grande"
        run.mkdir(parents=True)
        (run / ".kit-output").touch()
        manifest = {"estado": "completada_con_incidencias", "codigo_salida": 1, "motivo": None, "error": None,
                    "receta": {"nombre": "grande"}, "entradas": {}, "pasos": [
                        {"numero": i, "nombre": f"p{i:02d}", "op": "inspeccionar", "estado": "completado",
                         "carpeta": f"{i:02d}-p{i:02d}", "incidencias": 0, "advertencias": 0,
                         "filas": {"entrada": 1, "salidas": {}}, "invariantes": [], "trazas": {}}
                        for i in range(1, steps + 1)]}
        (run / "manifiesto.json").write_text(json.dumps(manifest), encoding="utf-8")
        detail_rows = [{"codigo": f"codigo_{i:02d}", "fila": i, "columna": "c", "origen": "x", "detalle": ""}
                       for i in range(codes)]
        (run / "report.json").write_text(json.dumps({"estado": "incidencias", "codigo_salida": 1, "comando": "ejecutar",
                                                     "filas_procesadas": 1, "incidencias": codes, "advertencias": 0,
                                                     "incidencias_detalle": detail_rows, "advertencias_detalle": []}),
                                         encoding="utf-8")
        long_rows = [{"codigo": "valor_no_unico", "fila": i, "columna": "orden", "origen": "x", "detalle": "d" * detail}
                     for i in range(2, 152)]
        (run / "incidencias.json").write_text(json.dumps({"columns": ["codigo", "fila", "columna", "origen", "detalle"],
                                                          "rows": long_rows}), encoding="utf-8")
        for i in range(files):
            (run / f"archivo_{i:02d}.csv").write_text("a\n", encoding="utf-8")
        return run

    def test_resultados_caps_steps_files_codes_issues_and_detail_length(self):
        self.fake_run()
        summary = json.loads(kit("resultados", "grande", "--output", self.out, "--json").stdout)
        self.assertEqual(len(summary["pasos"]), 30)
        self.assertEqual(len(summary["archivos"]), 40)
        self.assertEqual(len(summary["incidencias_por_codigo"]), 15)
        found = json.loads(kit("resultados", "grande", "--output", self.out, "--incidencias", "valor_no_unico",
                               "--n", "500", "--json").stdout)
        self.assertEqual((found["total"], found["mostradas"], found["limite"], found["maximo"]), (150, 100, 100, 100))
        self.assertEqual(len(found["elementos"]), 100)
        self.assertEqual({len(e["detalle"]) for e in found["elementos"]}, {200})
        text = kit("resultados", "grande", "--output", self.out, "--incidencias", "valor_no_unico", "--n", "500").stdout
        self.assertIn("100 de 150 (límite 100)", text)
        self.assertNotIn("d" * 201, text)


class PrivacidadRecetasTests(Base):
    VALORES = ["OT500", "OT501", "OT502", "OT503", "OT504", "OT505", "0099", "Bomba 50 m3/h", "Motor 75 kW",
               "Compresor 10 bar", "Compresor 12 bar", "2026-11-02", "2026-11-03", "2026-11-04"]

    def test_hidden_values_never_reach_terminal_or_json_summaries_of_example_recipes(self):
        result = kit("ejecutar", EJEMPLOS / "ordenes_flota.csv", "--receta", ROOT / "recetas" / "enriquecimiento_flota.json",
                     "--output", self.out, "--json", "--verbose", "--ocultar-valores", expected=1)
        self.assertEqual([v for v in self.VALORES if v in result.stdout + result.stderr], [])
        run = Path(json.loads(result.stdout)["ruta_resultados"])
        summaries = "\n".join(p.read_text(encoding="utf-8") for p in run.rglob("*.json")
                              if p.name in ("report.json", "manifiesto.json", "audit.json"))
        self.assertEqual([v for v in self.VALORES if v in summaries], [])
        shown = kit("resultados", run.name, "--output", self.out, "--incidencias", "clave_sin_coincidencia", "--json").stdout
        self.assertEqual(json.loads(shown)["total"], 1)
        self.assertEqual([v for v in self.VALORES if v in shown], [])
        # Control: sin la opción, los archivos de datos sí traen los valores (es su función).
        self.assertIn("Bomba 50 m3/h", (run / "01-enriquecer" / "completadas.csv").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

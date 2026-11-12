"""Pruebas de `ejecutar` (recetas) por la CLI. Resultados esperados calculados a mano."""
import contextlib
import csv
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kitlib import recetas
from kitlib.cli import main
from kitlib.runtime import configure

configure()

# Fila 2: OT001 correcta. Fila 3: orden repetida, fecha no ISO, horas -1 (3 incidencias).
# Fila 4: orden repetida, equipo vacío, horas 25 > 24 (3 incidencias).
ORDENES = ("orden;equipo;fecha;horas;estado\n"
           "OT001;0007;2026-10-01;2,5;abierta\n"
           "OT002;0012;03/04/2026;-1;abierta\n"
           "OT002;;2026-10-02;25;cerrada\n")
# Todas válidas: abiertas 0007 (2,5 + 1,5 = 4,0) y 0042 (3,0); OT005 cerrada no entra al resumen.
OTRAS = ("orden;equipo;fecha;horas;estado\n"
         "OT010;0007;2026-11-01;2,5;abierta\n"
         "OT011;0042;2026-11-02;3,0;abierta\n"
         "OT012;0007;2026-11-03;1,5;abierta\n"
         "OT013;0012;2026-11-04;8,0;cerrada\n")
ANTERIOR = ("orden;equipo;fecha;horas;estado\n"
            "OT001;0007;2026-10-01;2,0;abierta\n"
            "OT099;0099;2026-09-30;1,0;cerrada\n")
REGLAS = {"columns": {
    "orden": {"required": True, "nonempty": True, "unique": True},
    "equipo": {"required": True, "nonempty": True},
    "fecha": {"required": True, "nonempty": True, "type": "date"},
    "horas": {"required": True, "nonempty": True, "type": "number", "min": "0", "max": "24"},
    "estado": {"required": True, "nonempty": True}}}
PLAN = {"steps": [
    {"op": "filter", "column": "estado", "operator": "eq", "value": "abierta"},
    {"op": "group", "by": ["equipo"], "aggregates": [{"op": "count", "as": "ordenes"},
                                                    {"op": "sum", "column": "horas", "as": "horas"}]},
    {"op": "sort", "columns": ["equipo"]}]}


def receta(**cambios):
    base = {
        "version": 1, "nombre": "prueba",
        "entradas": {"ordenes": {"principal": True, "delimiter": ";", "decimal": ","},
                     "anterior": {"ruta": "anterior.csv", "delimiter": ";", "decimal": ","}},
        "pasos": [
            {"nombre": "perfil", "op": "inspeccionar", "entrada": "ordenes"},
            {"nombre": "revision", "op": "validar", "entrada": "ordenes", "reglas": "reglas.json",
             "politica": {"incidencias": "separar"}},
            {"nombre": "resumen", "op": "transformar", "entrada": "revision.aceptadas", "plan": PLAN},
            {"nombre": "cambios", "op": "comparar", "antes": "anterior", "despues": "revision.aceptadas",
             "clave": ["orden"]},
            {"nombre": "entrega", "op": "exportar", "archivo": "entrega", "formatos": ["csv", "xlsx"],
             "tablas": {"aceptadas": "revision.aceptadas", "rechazadas": "revision.rechazadas",
                        "resumen": "resumen.resultado"}}]}
    base.update(cambios)
    return base


class RecetaTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="recetas con espacios-", dir=ROOT / "tmp")
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.out = self.folder / "salidas"
        self.ordenes = self.write("órdenes.csv", ORDENES)
        self.write("anterior.csv", ANTERIOR)
        self.write("reglas.json", json.dumps(REGLAS))

    def write(self, name, content):
        path = self.folder / name
        path.write_text(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                        encoding="utf-8")
        return path

    def run_cli(self, recipe, input_path=None, *extra, expected=0):
        recipe_path = recipe if isinstance(recipe, Path) else self.write("receta.json", recipe)
        result = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), "ejecutar",
                                 str(input_path or self.ordenes), "--receta", str(recipe_path),
                                 "--output", str(self.out), "--json", *extra],
                                text=True, capture_output=True, cwd=ROOT, encoding="utf-8")
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def manifest(self, summary):
        return json.loads(Path(summary["manifiesto"]).read_text(encoding="utf-8"))

    def rows(self, path):
        with path.open(encoding="utf-8", newline="") as stream:
            return list(csv.reader(stream, delimiter=";"))

    def runs(self):
        return sorted(p.name for p in self.out.iterdir()) if self.out.exists() else []

    def hashes(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.folder.iterdir() if p.is_file()}

    def test_full_flow_separates_rows_and_never_labels_derived_tables_as_validated(self):
        recipe = self.write("receta.json", receta())
        before = self.hashes()
        summary = self.run_cli(recipe, expected=1)
        self.assertEqual(summary["estado"], "completada_con_incidencias")
        run = Path(summary["ruta_resultados"])
        m = self.manifest(summary)
        self.assertEqual((m["estado"], m["codigo_salida"], m["motivo"]), ("completada_con_incidencias", 1, None))
        self.assertEqual([p["estado"] for p in m["pasos"]],
                         ["completado", "completado_con_incidencias", "completado", "completado", "completado"])
        self.assertEqual(m["pasos"][1]["incidencias_por_codigo"], {
            "valor_no_unico": 2, "tipo_o_fecha_invalido": 1, "fuera_de_rango_min": 1, "campo_vacio": 1,
            "fuera_de_rango_max": 1})
        self.assertEqual(self.rows(run / "02-revision" / "aceptadas.csv")[1:], [
            ["OT001", "0007", "2026-10-01", "2,5", "abierta"]])
        self.assertEqual([r[0] for r in self.rows(run / "02-revision" / "rechazadas.csv")[1:]], ["OT002", "OT002"])
        self.assertEqual(self.rows(run / "03-resumen" / "resultado.csv"), [["equipo", "ordenes", "horas"],
                                                                          ["0007", "1", "2.5"]])
        # OT001 cambió de horas (2,0 → 2,5); OT099 solo estaba antes.
        self.assertEqual(m["pasos"][3]["conteos"], {"nuevos": 0, "eliminados": 1, "modificados": 1,
                                                   "sin_cambios": 0, "campos_cambiados": 1})
        exported = m["pasos"][4]["salidas"]
        self.assertEqual({k: (v["filas"], v["validada"]) for k, v in exported.items()},
                         {"aceptadas": (1, True), "rechazadas": (2, False), "resumen": (1, False)})
        self.assertTrue((run / "05-entrega" / "entrega.xlsx").is_file())
        self.assertEqual(m["pasos"][2]["salidas"]["resultado"]["validada"], False)  # transformado ≠ validado
        self.assertFalse((run / "FAILED.json").exists())
        self.assertEqual([p.name for p in run.iterdir() if p.name.endswith(".tmp")], [])
        self.assertEqual(self.hashes(), before)  # originales, reglas y receta intactos
        self.assertNotIn("0007", json.dumps(summary))  # el resumen no trae valores de celdas

    def test_same_recipe_on_another_file(self):
        recipe = self.write("receta.json", receta())
        first = self.run_cli(recipe, expected=1)
        other = self.run_cli(recipe, self.write("otras órdenes.csv", OTRAS))
        self.assertEqual(other["estado"], "completada")
        self.assertNotEqual(first["ruta_resultados"], other["ruta_resultados"])
        run = Path(other["ruta_resultados"])
        self.assertEqual(self.rows(run / "03-resumen" / "resultado.csv")[1:], [["0007", "2", "4.0"],
                                                                               ["0042", "1", "3.0"]])
        self.assertEqual(self.manifest(other)["pasos"][3]["conteos"]["nuevos"], 4)

    def test_invalid_recipe_reports_all_errors_and_creates_nothing(self):
        bad = receta(version=2, extra=True)
        bad["entradas"]["ordenes"]["decimal"] = ";"
        bad["pasos"][0]["op"] = "inspecionar"
        bad["pasos"][1]["politica"] = {"incidencias": "ignorar"}
        bad["pasos"][2]["plan"] = {"steps": [{"op": "group", "by": ["equipo"], "aggregates": []}]}
        bad["pasos"][4]["formatos"] = ["pdf"]
        summary = self.run_cli(bad, expected=2)
        codes = {(e["codigo"], e["paso"], e["campo"]) for e in summary["errores"]}
        self.assertTrue({("version_no_admitida", None, "version"), ("campo_desconocido", None, "extra"),
                         ("opcion_invalida", None, "entradas.ordenes.decimal"),
                         ("operacion_desconocida", "perfil", "op"),
                         ("politica_invalida", "revision", "paso.politica.incidencias"),
                         ("configuracion_invalida", "resumen", "plan"),
                         ("parametro_invalido", "entrega", "formatos")} <= codes, codes)
        hint = next(e for e in summary["errores"] if e["codigo"] == "operacion_desconocida")["sugerencia"]
        self.assertEqual(hint, "¿Quiso decir inspeccionar?")
        self.assertEqual(self.runs(), [])  # nada se creó
        missing = receta()
        del missing["version"]
        self.assertEqual(self.run_cli(missing, expected=2)["errores"][0]["codigo"], "version_ausente")
        self.write("rota.json", "{no es json")
        self.assertEqual(self.run_cli(self.folder / "rota.json", expected=2)["errores"][0]["codigo"],
                         "receta_json_invalido")
        self.assertEqual(self.runs(), [])

    def test_wrong_references_between_steps(self):
        bad = receta()
        bad["pasos"][2]["entrada"] = "revision.aceptada"     # errata
        bad["pasos"][1]["entrada"] = "resumen.resultado"     # paso posterior
        bad["pasos"][3]["despues"] = "perfil.resultado"      # inspeccionar no produce tablas
        bad["pasos"][4]["tablas"]["resumen"] = "nada"         # inexistente
        errors = {(e["paso"], e["campo"]): e for e in self.run_cli(bad, expected=2)["errores"]}
        self.assertEqual(errors["revision", "entrada"]["codigo"], "referencia_adelantada")
        self.assertEqual(errors["resumen", "entrada"]["codigo"], "salida_inexistente")
        self.assertEqual(errors["cambios", "despues"]["codigo"], "salida_inexistente")
        self.assertEqual(errors["cambios", "despues"]["sugerencia"], "Ese paso no produce tablas")
        self.assertEqual(errors["entrega", "tablas.resumen"]["codigo"], "referencia_inexistente")
        typo = receta()
        typo["pasos"][2]["entrada"] = "revision.aceptada"
        error = self.run_cli(typo, expected=2)["errores"][0]
        self.assertEqual((error["codigo"], error["paso"], error["campo"]), ("salida_inexistente", "resumen", "entrada"))
        self.assertIn("revision.aceptadas", error["sugerencia"])
        unused = receta()
        unused["pasos"] = unused["pasos"][:3]
        self.assertEqual(self.run_cli(unused, expected=2)["errores"][0]["codigo"], "entrada_sin_uso")
        separate = receta()
        separate["pasos"][3]["politica"] = {"incidencias": "separar"}
        self.assertEqual(self.run_cli(separate, expected=2)["errores"][0]["codigo"], "politica_no_aplicable")
        self.assertEqual(self.runs(), [])

    def test_intermediate_failure_leaves_failed_manifest_without_later_results(self):
        recipe = receta()
        recipe["pasos"][2]["plan"] = {"steps": [{"op": "convert", "column": "estado", "type": "number"}]}
        summary = self.run_cli(recipe, expected=2)
        m = self.manifest(summary)
        run = Path(summary["ruta_resultados"])
        self.assertEqual((m["estado"], m["motivo"]), ("fallida", "error_de_ejecucion"))
        self.assertEqual([p["estado"] for p in m["pasos"]],
                         ["completado", "completado_con_incidencias", "fallido", "pendiente", "pendiente"])
        self.assertEqual(m["error"]["paso"], "resumen")
        self.assertTrue((run / "FAILED.json").exists())
        self.assertFalse((run / "03-resumen" / "resultado.csv").exists())
        self.assertFalse((run / "04-cambios").exists())
        self.assertFalse((run / "05-entrega").exists())
        self.assertFalse((run / "report.json").exists())

    def test_default_policy_stops_on_issues_and_warnings_are_allowed_one_by_one(self):
        recipe = receta()
        del recipe["pasos"][1]["politica"]  # sin política: detener
        summary = self.run_cli(recipe, expected=2)
        m = self.manifest(summary)
        run = Path(summary["ruta_resultados"])
        self.assertEqual((m["estado"], m["motivo"]), ("fallida", "detenida_por_politica"))
        self.assertEqual([p["estado"] for p in m["pasos"]][1:3], ["detenido", "pendiente"])
        self.assertEqual(m["error"]["codigo"], "incidencias_no_admitidas")
        self.assertIn("separar", m["error"]["sugerencia"])
        self.assertTrue((run / "02-revision" / "incidencias.csv").exists())  # se puede revisar por qué
        self.assertFalse((run / "02-revision" / "aceptadas.csv").exists())  # pero no se publica la tabla

        def sql_recipe(allowed):
            return {"version": 1, "entradas": {"ordenes": {"delimiter": ";", "decimal": ","}},
                    "pasos": [{"nombre": "total", "op": "consultar", "tablas": {"t": "ordenes"},
                               "sql": "SELECT SUM(horas) AS total FROM t",
                               "politica": {"advertencias_permitidas": allowed}}]}
        # SUM sobre texto con coma decimal: advertencia resultado_depende_de_texto_sin_numeric.
        other_allowed = self.run_cli(sql_recipe(["valores_no_numericos_cargados_como_null"]), expected=2)
        self.assertEqual(self.manifest(other_allowed)["error"]["codigo"], "advertencias_no_admitidas")
        allowed = self.run_cli(sql_recipe(["resultado_depende_de_texto_sin_numeric"]), expected=1)
        m = self.manifest(allowed)
        self.assertEqual((m["estado"], m["pasos"][0]["estado"]), ("completada_con_incidencias",
                                                                  "completado_con_incidencias"))
        self.assertEqual(m["pasos"][0]["advertencias_por_codigo"], {"resultado_depende_de_texto_sin_numeric": 1})

    def test_entry_warnings_stop_unless_that_code_is_allowed(self):
        entry: dict = {}  # sin delimiter: una sola columna
        recipe = {"version": 1, "entradas": {"ordenes": entry},
                  "pasos": [{"nombre": "perfil", "op": "inspeccionar", "entrada": "ordenes"}]}
        source = self.write("punto y coma.csv", "orden;equipo\nOT1;0007\n")
        stopped = self.manifest(self.run_cli(recipe, source, expected=2))
        self.assertEqual((stopped["motivo"], stopped["error"]["paso"]), ("detenida_por_politica", "entrada ordenes"))
        self.assertEqual(stopped["pasos"][0]["estado"], "pendiente")
        entry["politica"] = {"advertencias_permitidas": ["posible_delimitador_incorrecto"]}
        self.assertEqual(self.run_cli(recipe, source, expected=1)["estado"], "completada_con_incidencias")
        # Con comas decimales además hay filas de ancho incorrecto: incidencia, no advertencia.
        self.assertEqual(self.manifest(self.run_cli(recipe, expected=2))["error"]["codigo"], "incidencias_no_admitidas")

    def test_preview_reads_no_data_and_writes_nothing(self):
        summary = self.run_cli(receta(), None, "--vista-previa")
        self.assertEqual((summary["estado"], summary["datos_leidos"]), ("vista_previa", False))
        self.assertIn("NO se leyeron", summary["aviso"])
        self.assertEqual([s["nombre"] for s in summary["pasos"]], ["perfil", "revision", "resumen", "cambios", "entrega"])
        self.assertEqual(summary["pasos"][1]["politica"]["incidencias"], "separar")
        self.assertIn("05-entrega/entrega.xlsx", summary["pasos"][4]["destino"])
        self.assertEqual(self.runs(), [])
        # Un archivo con datos inválidos pasa la vista previa: no es una validación de datos.
        self.write("basura.csv", "x\n\x00\n")
        self.assertEqual(self.run_cli(receta(), self.folder / "basura.csv", "--vista-previa")["estado"], "vista_previa")
        self.assertEqual(self.runs(), [])

    def test_manifest_is_in_progress_while_running_and_interruption_is_recorded(self):
        recipe_path = self.write("receta.json", receta())
        seen = []
        original = recetas.RUNNERS["transformar"]

        def spy(step, get):
            run = next(self.out.iterdir())
            seen.append(json.loads((run / "manifiesto.json").read_text(encoding="utf-8"))["estado"])
            return original(step, get)

        def interrupt(step, get):
            raise KeyboardInterrupt

        args = [ "ejecutar", str(self.ordenes), "--receta", str(recipe_path), "--output", str(self.out), "--json"]
        with mock.patch.dict(recetas.RUNNERS, {"transformar": spy}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 1)
        self.assertEqual(seen, ["en_curso"])  # un corte en ese momento no parece terminado
        with mock.patch.dict(recetas.RUNNERS, {"comparar": interrupt}), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                main(args + ["--run-name", "interrumpida"])
        m = json.loads((self.out / "interrumpida" / "manifiesto.json").read_text(encoding="utf-8"))
        self.assertEqual((m["estado"], m["motivo"]), ("fallida", "interrumpida"))
        self.assertEqual([p["estado"] for p in m["pasos"]][2:], ["completado", "interrumpido", "pendiente"])
        self.assertTrue((self.out / "interrumpida" / "FAILED.json").exists())

    def test_example_recipe_in_repository(self):
        example = ROOT / "recetas" / "revision_ordenes.json"
        summary = self.run_cli(example, ROOT / "examples" / "con incidencias.csv", expected=1)
        self.assertEqual([p["filas"] for p in summary["pasos"]][1],
                         {"aceptadas": 1, "rechazadas": 2, "incidencias": 6})


if __name__ == "__main__":
    unittest.main()

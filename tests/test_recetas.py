"""Pruebas de `ejecutar` (recetas) por la CLI. Resultados esperados calculados a mano."""
import contextlib
import csv
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kitlib import __version__, recetas
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


class Base(unittest.TestCase):
    """Carpeta temporal, archivos de prueba y ayudantes; sin pruebas propias."""

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


class RecetaTests(Base):
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
        self.assertEqual(self.rows(run / "02-revision" / "rechazadas.csv")[1:], [
            ["OT002", "0012", "03/04/2026", "-1", "abierta"], ["OT002", "", "2026-10-02", "25", "cerrada"]])
        found = {(r[1], r[2], r[0]) for r in self.rows(run / "02-revision" / "incidencias.csv")[1:]}
        self.assertEqual(found, {("3", "orden", "valor_no_unico"), ("4", "orden", "valor_no_unico"),
                                 ("4", "equipo", "campo_vacio"), ("3", "fecha", "tipo_o_fecha_invalido"),
                                 ("3", "horas", "fuera_de_rango_min"), ("4", "horas", "fuera_de_rango_max")})
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
        printed = json.dumps(summary, ensure_ascii=False)  # el resumen no trae valores de celdas
        for value in ("OT001", "OT002", "0007", "0012", "2026-10-01", "03/04/2026", "2,5", "abierta", "cerrada"):
            self.assertNotIn(value, printed)

    def test_same_recipe_on_another_file(self):
        recipe = self.write("receta.json", receta())
        first = self.run_cli(recipe, expected=1)
        other = self.run_cli(recipe, self.write("otras órdenes.csv", OTRAS))
        self.assertEqual(other["estado"], "completada")
        self.assertNotEqual(first["ruta_resultados"], other["ruta_resultados"])
        run = Path(other["ruta_resultados"])
        self.assertEqual(self.rows(run / "03-resumen" / "resultado.csv")[1:], [["0007", "2", "4.0"],
                                                                               ["0042", "1", "3.0"]])
        # Antes: OT001 y OT099; después: OT010–OT013. Ninguna clave en común.
        self.assertEqual(self.manifest(other)["pasos"][3]["conteos"], {
            "nuevos": 4, "eliminados": 2, "modificados": 0, "sin_cambios": 0, "campos_cambiados": 0})

    def test_invalid_recipe_reports_all_errors_and_creates_nothing(self):
        bad = receta(version=2, extra=True)
        bad["entradas"]["ordenes"]["decimal"] = ";"
        bad["pasos"][0]["op"] = "inspecionar"
        bad["pasos"][1]["politica"] = {"incidencias": "ignorar"}
        bad["pasos"][2]["plan"] = {"steps": [{"op": "group", "by": ["equipo"], "aggregates": []}]}
        bad["pasos"][4]["formatos"] = ["pdf"]
        summary = self.run_cli(bad, expected=2)
        codes = {(e["codigo"], e["paso"], e["campo"]) for e in summary["errores"]}
        self.assertEqual(codes, {("version_no_admitida", None, "version"), ("campo_desconocido", None, "extra"),
                                 ("opcion_invalida", None, "entradas.ordenes.decimal"),
                                 ("operacion_desconocida", "perfil", "op"),
                                 ("politica_invalida", "revision", "paso.politica.incidencias"),
                                 ("configuracion_invalida", "resumen", "plan"),
                                 ("parametro_invalido", "entrega", "formatos")})
        self.assertEqual(summary["total_errores"], 7)
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
        self.assertEqual(m["pasos"][0]["participacion"]["tablas_leidas"], ["t"])  # traza solo en recetas

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
        self.assertEqual({s["columnas"] for s in summary["pasos"]}, {"comprobadas"})
        self.assertEqual((summary["errores"], summary["avisos"]), ([], []))
        # Encabezado correcto y filas inválidas: pasa la vista previa, que no es una validación de datos.
        bad_rows = self.write("filas malas.csv", "orden;equipo;fecha;horas;estado\nOT1;;ayer;mucho;\n\"roto\n")
        self.assertEqual(self.run_cli(receta(), bad_rows, "--vista-previa")["codigo_salida"], 0)
        self.assertEqual(self.runs(), [])

    def test_preview_and_run_check_referenced_columns_from_headers(self):
        # Sin "estado": el filtro del plan falla. Sin "fecha": validar dará columna_obligatoria_ausente.
        source = self.write("sin estado.csv", "orden;equipo;horas\nOT1;0007;1,0\n")
        preview = self.run_cli(receta(), source, "--vista-previa", expected=2)
        by_step = {s["nombre"]: s for s in preview["pasos"]}
        self.assertEqual(by_step["perfil"]["columnas"], "comprobadas")
        self.assertEqual(by_step["revision"]["incidencias_previstas"], ["columna_obligatoria_ausente"])
        self.assertEqual((by_step["resumen"]["columnas"], by_step["resumen"]["motivo"]),
                         ("error", "Columnas inexistentes: estado"))
        self.assertEqual(by_step["cambios"]["columnas"], "comprobadas")  # comparar usa aceptadas: mismas columnas
        self.assertEqual(by_step["entrega"]["columnas"], "no_comprobadas")  # depende de resumen
        self.assertEqual([(e["codigo"], e["paso"]) for e in preview["errores"]], [("columnas_incompatibles", "resumen")])
        failed = self.run_cli(receta(), source, expected=2)  # ejecutar también comprueba antes de crear nada
        self.assertEqual(failed["errores"][0]["codigo"], "columnas_incompatibles")
        self.assertEqual(self.runs(), [])
        # Clave de comparar y SQL también se comprueban con el encabezado.
        recipe = receta()
        recipe["pasos"][3]["clave"] = ["Orden"]
        recipe["pasos"].insert(3, {"nombre": "sql", "op": "consultar", "tablas": {"t": "ordenes"},
                                   "sql": "SELECT turno FROM t"})
        errors = {e["paso"]: e["mensaje"] for e in self.run_cli(recipe, None, "--vista-previa", expected=2)["errores"]}
        self.assertEqual(set(errors), {"sql", "cambios"})
        self.assertIn("turno", errors["sql"])
        self.assertIn("Orden", errors["cambios"])
        # JSON no se puede leer solo por el encabezado: la vista previa lo dice.
        table = self.write("ordenes.json", {"columns": ["orden"], "rows": [{"orden": "OT1"}]})
        only = {"version": 1, "entradas": {"ordenes": {}},
                "pasos": [{"nombre": "perfil", "op": "inspeccionar", "entrada": "ordenes"}]}
        summary = self.run_cli(only, table, "--vista-previa")
        self.assertEqual((summary["entradas"][0]["encabezado"], summary["pasos"][0]["columnas"]),
                         ("no_comprobado", "no_comprobadas"))
        self.assertFalse(summary["encabezados_leidos"])
        self.assertIn("Encabezados no comprobados: ordenes", summary["aviso"])

    def test_killed_process_leaves_manifest_in_progress_and_no_complete_partial_tables(self):
        recipe_path = self.write("receta.json", receta())
        marker = self.folder / "dentro.txt"
        # Proceso real: al llegar a escribir el xlsx de "entrega" (ya escritos sus CSV) avisa y espera.
        script = ("import sys, time, pathlib\n"
                  f"sys.path.insert(0, {str(ROOT / 'src')!r})\n"
                  "from kitlib.runtime import configure\nconfigure()\n"
                  "from kitlib import recetas\nfrom kitlib.cli import main\n"
                  "def lenta(path, tables):\n"
                  "    pathlib.Path(sys.argv[1]).write_text('dentro')\n"
                  "    time.sleep(120)\n"
                  "recetas.excel_write = lenta\n"
                  "sys.exit(main(sys.argv[2:]))\n")
        process = subprocess.Popen([sys.executable, "-B", "-c", script, str(marker), "ejecutar", str(self.ordenes),
                                    "--receta", str(recipe_path), "--output", str(self.out), "--run-name", "cortada",
                                    "--json"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ in range(600):
                if marker.exists() or process.poll() is not None:
                    break
                time.sleep(0.1)
            self.assertTrue(marker.exists(), "el proceso no llegó al punto de corte")
        finally:
            process.kill()  # SIGKILL en Linux, TerminateProcess en Windows: sin limpieza posible
            out, _ = process.communicate()
        self.assertEqual(out, b"")  # no llegó a imprimir ningún resumen
        run = self.out / "cortada"
        m = json.loads((run / "manifiesto.json").read_text(encoding="utf-8"))
        self.assertEqual((m["estado"], m["codigo_salida"], m["fin_utc"]), ("en_curso", None, None))
        self.assertEqual([p["estado"] for p in m["pasos"]],
                         ["completado", "completado_con_incidencias", "completado", "completado", "en_curso"])
        self.assertNotIn("salidas", m["pasos"][4])
        self.assertTrue((run / "05-entrega" / "aceptadas.csv").exists())  # archivos parciales en disco…
        listed = {f.split("#")[0] for p in m["pasos"] for s in p.get("salidas", {}).values()
                  for f in s.get("archivos", [s.get("archivo")])}
        self.assertFalse(any(f.startswith("05-entrega") for f in listed))  # …que nada presenta como resultado
        for name in ("report.json", "audit.json", "FAILED.json"):
            self.assertFalse((run / name).exists(), name)
        self.assertEqual([p.name for p in run.iterdir() if p.name.endswith(".tmp")], [])

    def test_manifest_is_in_progress_while_running_and_interruption_is_recorded(self):
        recipe_path = self.write("receta.json", receta())
        seen = []
        original = recetas.RUNNERS["transformar"]

        def spy(step, get):
            # También se llama en la comprobación previa de columnas, antes de crear la carpeta.
            run = next(self.out.iterdir(), None) if self.out.exists() else None
            seen.append(json.loads((run / "manifiesto.json").read_text(encoding="utf-8"))["estado"]
                        if run else "antes_de_crear")
            return original(step, get)

        def interrupt(step, get):
            if (self.out / "interrumpida").exists():  # durante la ejecución, no en la comprobación previa
                raise KeyboardInterrupt
            return recetas._step_comparar(step, get)

        args = [ "ejecutar", str(self.ordenes), "--receta", str(recipe_path), "--output", str(self.out), "--json"]
        with mock.patch.dict(recetas.RUNNERS, {"transformar": spy}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 1)
        self.assertEqual(seen, ["antes_de_crear", "en_curso"])  # un corte en ese momento no parece terminado
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


# --- Trazabilidad (1.5.0-etapa2). Escenario calculado a mano:
# turno A: fila 2 OT1 abierta 2,5 | fila 3 OT2 cerrada 1,0 | fila 4 OT3 horas "x" (inválida)
# turno B: fila 2 OT4 abierta 4,0 | fila 3 OT1 repetida | fila 4 OT5 abierta 1,5
# validar rechaza A4. limpieza: convierte 5 horas, el filtro excluye A3 (cerrada), deduplicar excluye B3.
# resumen: 0007 = A2 + B4 = 2.5 + 1.5 = 4.0; 0042 = B2 = 4.0. comparar con anterior: OT1 cambia, OT9 se va.
TURNO_A = ("orden;equipo;fecha;horas;estado\nOT1;0007;2026-10-01;2,5;abierta\nOT2;0012;2026-10-01;1,0;cerrada\n"
           "OT3;0007;2026-10-02;x;abierta\n")
TURNO_B = ("orden;equipo;fecha;horas;estado\nOT4;0042;2026-10-03;4,0;abierta\nOT1;0007;2026-10-01;2,5;abierta\n"
           "OT5;0007;2026-10-04;1,5;abierta\n")
ANTERIOR_PUNTO = "orden;equipo;fecha;horas;estado\nOT1;0007;2026-10-01;2.0;abierta\nOT9;0099;2026-09-30;1.0;cerrada\n"
BUSINESS = ["orden", "equipo", "fecha", "horas", "estado"]


class TrazaTests(Base):
    def setUp(self):
        super().setUp()
        self.a = self.write("turno A.csv", TURNO_A)
        self.b = self.write("turno B.csv", TURNO_B)
        self.write("anterior punto.csv", ANTERIOR_PUNTO)

    def recipe(self):
        semicolon = {"delimiter": ";", "decimal": ","}
        return {"version": 1, "nombre": "traza",
                "entradas": {"turno_a": {"principal": True, **semicolon}, "turno_b": {"ruta": "turno B.csv", **semicolon},
                             "anterior": {"ruta": "anterior punto.csv", "delimiter": ";"}},
                "pasos": [
                    {"nombre": "union", "op": "consolidar", "entradas": ["turno_a", "turno_b"]},
                    {"nombre": "revision", "op": "validar", "entrada": "union.resultado",
                     "reglas": {"columns": {"horas": {"type": "number"}, "orden": {"nonempty": True}}},
                     "politica": {"incidencias": "separar"}},
                    {"nombre": "limpieza", "op": "transformar", "entrada": "revision.aceptadas", "plan": {"steps": [
                        {"op": "convert", "column": "horas", "type": "number"},
                        {"op": "filter", "column": "estado", "operator": "eq", "value": "abierta"},
                        {"op": "deduplicate", "keys": ["orden"]},
                        {"op": "select", "columns": BUSINESS}]}},
                    {"nombre": "resumen", "op": "transformar", "entrada": "limpieza.resultado", "traza": "detallada",
                     "opciones": {"decimal": "."}, "plan": {"steps": [
                         {"op": "group", "by": ["equipo"], "aggregates": [{"op": "sum", "column": "horas", "as": "horas"}]},
                         {"op": "sort", "columns": ["equipo"]}]}},
                    {"nombre": "cambios", "op": "comparar", "antes": "anterior", "despues": "limpieza.resultado",
                     "clave": ["orden"]}]}

    def test_real_provenance_excluded_rows_cell_changes_and_invariants(self):
        before = self.hashes()
        summary = self.run_cli(self.recipe(), self.a, expected=1)
        run, m = Path(summary["ruta_resultados"]), self.manifest(summary)
        steps = {p["nombre"]: p for p in m["pasos"]}
        a, b, old = str(self.a.resolve()), str(self.b.resolve()), str((self.folder / "anterior punto.csv").resolve())

        def origin_rows(path):
            return [r[1:4] for r in self.rows(path)[1:]]

        # consolidar: columnas de procedencia existentes, ahora con el archivo y la fila reales.
        union = self.rows(run / "01-union" / "resultado.csv")
        self.assertEqual([(r[5], r[6]) for r in union[1:]], [(a, "2"), (a, "3"), (a, "4"), (b, "2"), (b, "3"), (b, "4")])
        # validar: la incidencia y el motivo citan el archivo y la fila originales, no la fila 4 de la unión.
        self.assertEqual([(r[0], r[1], r[2], r[3]) for r in self.rows(run / "02-revision" / "incidencias.csv")[1:]],
                         [("tipo_o_fecha_invalido", "4", "horas", a)])
        self.assertEqual(self.rows(run / "02-revision" / "rechazadas_procedencia.csv")[1:],
                         [["2", "turno_a", a, "4", "tipo_o_fecha_invalido"]])
        self.assertEqual(origin_rows(run / "02-revision" / "aceptadas_procedencia.csv"),
                         [["turno_a", a, "2"], ["turno_a", a, "3"], ["turno_b", b, "2"], ["turno_b", b, "3"],
                          ["turno_b", b, "4"]])
        self.assertEqual(steps["revision"]["invariantes"][0] | {"regla": ""}, {
            "tipo": "particion", "regla": "", "entrada": 6, "aceptadas": 5, "rechazadas": 1, "cumple": True})
        # limpieza: filas excluidas con motivo y fila original; cambios de celdas revisables.
        excluded = self.rows(run / "03-limpieza" / "excluidas.csv")
        self.assertEqual(excluded[0], ["paso_plan", "operacion", "motivo", "entrada", "archivo", "fila_origen",
                                       *BUSINESS, "__archivo_origen", "__fila_origen"])
        self.assertEqual([r[:6] for r in excluded[1:]], [
            ["2", "filter", "no cumple estado eq abierta", "turno_a", a, "3"],
            ["3", "deduplicate", "repite la clave orden de la fila conservada (turno_a fila 2)", "turno_b", b, "3"]])
        self.assertEqual(excluded[1][6:11], ["OT2", "0012", "2026-10-01", "1.0", "cerrada"])  # tal como estaba
        self.assertEqual(self.rows(run / "03-limpieza" / "cambios_celdas.csv")[1:], [
            ["turno_a", a, "2", "horas", "2,5", "2.5", "convert number", "1"],
            ["turno_a", a, "3", "horas", "1,0", "1.0", "convert number", "1"],
            ["turno_b", b, "2", "horas", "4,0", "4.0", "convert number", "1"],
            ["turno_b", b, "3", "horas", "2,5", "2.5", "convert number", "1"],
            ["turno_b", b, "4", "horas", "1,5", "1.5", "convert number", "1"]])
        self.assertEqual(self.rows(run / "03-limpieza" / "resultado.csv")[0], BUSINESS)  # sin columnas añadidas
        self.assertEqual(origin_rows(run / "03-limpieza" / "resultado_procedencia.csv"),
                         [["turno_a", a, "2"], ["turno_b", b, "2"], ["turno_b", b, "4"]])
        self.assertEqual(steps["limpieza"]["filas"], {"entrada": 5, "salidas": {"resultado": 3}, "excluidas": 2,
                                                      "cambios_celdas": 5})
        self.assertEqual((steps["limpieza"]["invariantes"][0]["tipo"], steps["limpieza"]["invariantes"][0]["cumple"]),
                         ("particion", True))
        # agregado: sin procedencia por fila, pero participantes reconstruibles; no es una partición.
        self.assertEqual(self.rows(run / "04-resumen" / "resultado.csv")[1:], [["0007", "4.0"], ["0042", "4.0"]])
        self.assertEqual(self.rows(run / "04-resumen" / "participantes.csv")[1:], [
            ["1", '{"equipo": "0007"}', "turno_a", a, "2"], ["1", '{"equipo": "0007"}', "turno_b", b, "4"],
            ["1", '{"equipo": "0042"}', "turno_b", b, "2"]])
        self.assertFalse((run / "04-resumen" / "resultado_procedencia.csv").exists())
        self.assertEqual(steps["resumen"]["trazas"]["resultado"], "sin procedencia individual (agregado)")
        self.assertEqual(steps["resumen"]["invariantes"][0]["tipo"], "participacion")
        # cruce: nuevas, eliminadas y cambios con su fila original de antes y de después.
        self.assertEqual(origin_rows(run / "05-cambios" / "nuevos_procedencia.csv"), [["turno_b", b, "2"],
                                                                                     ["turno_b", b, "4"]])
        self.assertEqual(origin_rows(run / "05-cambios" / "eliminados_procedencia.csv"), [["anterior", old, "3"]])
        self.assertEqual(self.rows(run / "05-cambios" / "cambios_procedencia.csv")[1:],
                         [["2", "anterior", old, "2", "turno_a", a, "2"]])
        self.assertEqual(steps["cambios"]["invariantes"][0]["tipo"], "claves")
        # La procedencia interna nunca se publica en las tablas de negocio.
        for path in run.rglob("*.json"):
            self.assertNotIn("\\u0000", path.read_text(encoding="utf-8"), path)
        # Manifiesto: parámetros, versión, receta y dónde están los detalles; terminal acotada y sin celdas.
        self.assertEqual((m["version_kit"], m["parametros"]["command"]), (__version__, "ejecutar"))
        self.assertEqual(steps["limpieza"]["detalles"], "03-limpieza/report.json")
        self.assertEqual([p["excluidas"] for p in summary["pasos"]], [0, 0, 2, 0, 0])
        printed = json.dumps(summary, ensure_ascii=False)
        for value in ("OT1", "OT2", "0007", "2,5", "abierta", "cerrada"):
            self.assertNotIn(value, printed)
        self.assertEqual(self.hashes(), {**before, "receta.json": self.hashes()["receta.json"]})

    def test_malformed_entry_rows_keep_real_row_numbers(self):
        source = self.write("con fila rota.csv", "orden;horas\nOT1;1\nOT2;2;extra\nOT3;3\n")
        recipe = {"version": 1, "entradas": {"ordenes": {"delimiter": ";", "politica": {"incidencias": "separar"}}},
                  "pasos": [{"nombre": "revision", "op": "validar", "entrada": "ordenes",
                             "reglas": {"columns": {"horas": {"type": "integer"}}}},
                            # aceptadas está renumerada (2, 3): consolidar debe citar las filas reales (2, 4).
                            {"nombre": "union", "op": "consolidar", "entradas": ["revision.aceptadas"]}]}
        summary = self.run_cli(recipe, source, expected=1)
        run, m = Path(summary["ruta_resultados"]), self.manifest(summary)
        entry = m["entradas"]["ordenes"]
        self.assertEqual((entry["filas_leidas"], entry["filas_tabulares"], entry["filas_excluidas_mal_formadas"]),
                         (3, 2, 1))
        self.assertTrue(entry["invariante"]["cumple"])
        self.assertEqual([r[0] for r in self.rows(run / "00-entradas" / "incidencias.csv")[1:]], ["ancho_incorrecto"])
        self.assertEqual([r[3] for r in self.rows(run / "01-revision" / "aceptadas_procedencia.csv")[1:]], ["2", "4"])
        self.assertEqual([(r[2], r[3]) for r in self.rows(run / "02-union" / "resultado.csv")[1:]],
                         [(str(source.resolve()), "2"), (str(source.resolve()), "4")])

    def test_broken_invariant_fails_the_step_without_publishing_tables(self):
        from kitlib import operations

        def loses_a_row(table, config, opts):
            tables, issues, details = operations.validate(table, config, opts)
            if tables["invalidos"].rows:  # (vacía en la comprobación previa de columnas)
                tables["invalidos"].rows.pop()  # una fila rechazada desaparece
            return tables, issues, details

        def hides_an_exclusion(table, plan, opts, trace=None):
            result = operations.transform(table, plan, opts, trace)
            if trace is not None and trace["excluidas"]:
                trace["excluidas"].pop()
            return result

        recipe_path = self.write("receta.json", self.recipe())
        for name, target, fake, folder in (("validar", "validate", loses_a_row, "02-revision"),
                                           ("transformar", "transform", hides_an_exclusion, "03-limpieza")):
            args = ["ejecutar", str(self.a), "--receta", str(recipe_path), "--output", str(self.out),
                    "--run-name", name, "--json"]
            with mock.patch.object(recetas, target, fake), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 2)
            run = self.out / name
            m = json.loads((run / "manifiesto.json").read_text(encoding="utf-8"))
            failed = next(p for p in m["pasos"] if p["estado"] == "fallido")
            self.assertEqual((m["estado"], m["motivo"], failed["carpeta"]), ("fallida", "error_de_ejecucion", folder))
            self.assertIn("Invariante incumplida", m["error"]["mensaje"])
            self.assertFalse(failed["invariantes"][0]["cumple"])
            self.assertEqual(sorted(p.name for p in (run / folder).iterdir() if p.name.endswith((".csv", ".json"))
                                    and not p.name.startswith(("incidencias", "report"))), [])
            self.assertTrue((run / "FAILED.json").exists())


if __name__ == "__main__":
    unittest.main()

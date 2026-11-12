"""Transformaciones controladas (1.5.0-etapa3) por la CLI. Resultados esperados escritos a mano."""
import hashlib
import subprocess
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_recetas import ROOT, Base  # ayudantes comunes: carpeta temporal, run_cli, rows, manifest

SEMI = {"delimiter": ";", "decimal": ","}


def plan_recipe(*steps, entry=None, **step_extra):
    """Receta de una entrada y un paso transformar con el plan indicado."""
    return {"version": 1, "entradas": {"ordenes": {"principal": True, **SEMI, **(entry or {})}},
            "pasos": [{"nombre": "paso", "op": "transformar", "entrada": "ordenes",
                       "plan": {"steps": list(steps)}, **step_extra}]}


class RenombrarTests(Base):
    DATA = "Orden;Equipo;horas\nOT1;0007;1,5\nOT2;0012;2,0\n"

    def test_rename_keeps_values_codes_and_real_provenance(self):
        source = self.write("cabeceras.csv", self.DATA)
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        summary = self.run_cli(plan_recipe({"op": "rename", "columns": {"Orden": "orden", "Equipo": "equipo"}}), source)
        run = Path(summary["ruta_resultados"])
        self.assertEqual(self.rows(run / "01-paso" / "resultado.csv"),
                         [["orden", "equipo", "horas"], ["OT1", "0007", "1,5"], ["OT2", "0012", "2,0"]])
        self.assertEqual([r[3] for r in self.rows(run / "01-paso" / "resultado_procedencia.csv")[1:]], ["2", "3"])
        step = self.manifest(summary)["pasos"][0]
        self.assertTrue(step["invariantes"][0]["cumple"])
        self.assertEqual(step["filas"]["cambios_celdas"], 0)  # renombrar no cambia celdas
        report = json.loads((run / "01-paso" / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["detalle"]["pasos"][0]["renombradas"], {"Orden": "orden", "Equipo": "equipo"})
        # Intercambio explícito: válido, cada valor queda bajo su nombre nuevo.
        swap = self.run_cli(plan_recipe({"op": "rename", "columns": {"Orden": "Equipo", "Equipo": "Orden"}}), source)
        self.assertEqual(self.rows(Path(swap["ruta_resultados"]) / "01-paso" / "resultado.csv")[:2],
                         [["Equipo", "Orden", "horas"], ["OT1", "0007", "1,5"]])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_rename_collisions_and_ambiguities_are_actionable_errors(self):
        source = self.write("cabeceras.csv", self.DATA)
        # Dos columnas con el mismo nombre de salida: error de receta, antes de leer datos.
        same = self.run_cli(plan_recipe({"op": "rename", "columns": {"Orden": "x", "Equipo": "x"}}), source,
                            expected=2)
        error = same["errores"][0]
        self.assertEqual((error["codigo"], error["paso"], error["campo"]), ("configuracion_invalida", "paso", "plan"))
        self.assertIn("mismo nombre: x", error["mensaje"])
        self.assertTrue(error["sugerencia"])
        # Choque con una columna existente no renombrada, y origen inexistente (mayúsculas cuentan):
        # se detectan con el encabezado, en vista previa y antes de crear la ejecución.
        for mapping, expected_text in (({"Orden": "horas"}, "choca con una columna existente: horas"),
                                       ({"orden": "pedido"}, "Columnas inexistentes: orden")):
            recipe = plan_recipe({"op": "rename", "columns": mapping})
            preview = self.run_cli(recipe, source, "--vista-previa", expected=2)
            self.assertEqual([(e["codigo"], e["paso"]) for e in preview["errores"]], [("columnas_incompatibles", "paso")])
            self.assertIn(expected_text, preview["errores"][0]["mensaje"])
            self.assertEqual(self.run_cli(recipe, source, expected=2)["errores"][0]["codigo"], "columnas_incompatibles")
        # Columna de origen repetida en el mapeo: JSON no la distingue; se rechaza en vez de "gana la última".
        raw = json.dumps(plan_recipe({"op": "rename", "columns": {"Orden": "a"}}))
        self.write("repetida.json", raw.replace('{"Orden": "a"}', '{"Orden": "a", "Orden": "b"}'))
        repeated = self.run_cli(self.folder / "repetida.json", source, expected=2)["errores"][0]
        self.assertEqual(repeated["codigo"], "clave_json_repetida")
        self.assertIn("Orden", repeated["mensaje"])
        self.write("plan repetido.json", '{"steps": [{"op": "rename", "columns": {"Orden": "a", "Orden": "b"}}]}')
        external = self.run_cli(plan_recipe() | {"pasos": [{"nombre": "paso", "op": "transformar", "entrada": "ordenes",
                                                             "plan": "plan repetido.json"}]}, source, expected=2)
        self.assertEqual(external["errores"][0]["codigo"], "configuracion_invalida")
        self.assertIn("Clave JSON repetida: Orden", external["errores"][0]["mensaje"])
        self.assertEqual(self.runs(), [])

    def test_rename_in_plain_transform_command_and_repeated_rule_keys(self):
        source = self.write("cabeceras.csv", self.DATA)
        plan = self.write("plan.json", {"steps": [{"op": "rename", "columns": {"Orden": "orden"}}]})
        result = self.cli_plain("transformar", source, "--plan", plan)
        self.assertEqual(self.rows(Path(result["ruta_resultados"]) / "validos.csv")[0], ["orden", "Equipo", "horas"])
        # Cambio de compatibilidad documentado: reglas con una columna repetida ya no se aceptan en silencio.
        rules = self.write("reglas.json", '{"columns": {"horas": {"type": "number"}, "horas": {"type": "string"}}}')
        failed = self.cli_plain("validar", source, "--rules", rules, expected=2)
        self.assertIn("Clave JSON repetida: horas", failed["error"])

    def cli_plain(self, command, source, *extra, expected=0):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), command, str(source), "--delimiter", ";",
                                 "--output", str(self.out), "--json", *map(str, extra)],
                                text=True, capture_output=True, cwd=ROOT, encoding="utf-8")
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)


if __name__ == "__main__":
    unittest.main()

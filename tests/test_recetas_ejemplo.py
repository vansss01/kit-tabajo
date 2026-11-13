"""Recetas de ejemplo del repositorio (recetas/*.json) sobre sus entradas ficticias (examples/recetas/),
comparadas por la CLI contra resultados escritos a mano en examples/recetas/esperados/*.json.

Cada esperado describe: estado y código de salida, estado y filas de cada paso, conteos por código,
columnas completas de algunas tablas (`columnas`), filas completas de otras (`tablas`), las incidencias
exactas (fila, columna, código) y los exportes. `otra_entrada` repite la receta sobre un segundo archivo
compatible cambiando solo la ruta (y, si hace falta, `--entrada`)."""
import csv
import hashlib
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
ESPERADOS = ROOT / "examples" / "recetas" / "esperados"
RECETAS = sorted(p.stem for p in (ROOT / "recetas").glob("*.json"))


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.reader(stream, delimiter=";"))


def column(table, name):
    header = table[0]
    return [row[header.index(name)] for row in table[1:]]


class RecetasEjemploTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="recetas ejemplo-", dir=ROOT / "tmp")
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name) / "salidas"

    def run_recipe(self, recipe, expected, principal, entradas):
        command = [sys.executable, "-B", str(ROOT / "kit.py"), "ejecutar", str(ROOT / principal), "--receta",
                   str(ROOT / recipe), "--output", str(self.out), "--json"]
        for name, path in entradas.items():
            command += ["--entrada", f"{name}={ROOT / path}"]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, expected["codigo_salida"], result.stdout + result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["estado"], expected["estado"])
        return summary, Path(summary["ruta_resultados"])

    def check(self, expected, summary, run):
        manifest = json.loads((run / "manifiesto.json").read_text(encoding="utf-8"))
        steps = {p["nombre"]: p for p in manifest["pasos"]}
        printed_steps = {p["nombre"]: p for p in summary["pasos"]}
        for name, want in expected["pasos"].items():
            step = steps[name]
            self.assertEqual(step["estado"], want["estado"], name)
            if "filas" in want:  # el resumen de ejecutar cuenta también la tabla de incidencias
                self.assertEqual(printed_steps[name]["filas"], want["filas"], name)
            if "incidencias_por_codigo" in want:
                self.assertEqual(step["incidencias_por_codigo"], want["incidencias_por_codigo"], name)
                self.assertEqual(step["incidencias"], sum(want["incidencias_por_codigo"].values()), name)
        for relative, columns in expected.get("columnas", {}).items():
            table = rows(run / relative)
            for col, values in columns.items():
                self.assertEqual(column(table, col), values, relative + " " + col)
        for relative, wanted in expected.get("incidencias", {}).items():
            table = rows(run / relative)
            found = sorted((r[1], r[2], r[0]) for r in table[1:])  # fila, columna, codigo
            self.assertEqual(found, sorted(tuple(w) for w in wanted), relative)
        for relative, wanted in expected.get("tablas", {}).items():
            self.assertEqual(rows(run / relative), wanted, relative)
        for relative in expected.get("exportados", []):
            self.assertTrue((run / relative).is_file(), relative)
        self.assertTrue(all(c["cumple"] for p in manifest["pasos"] for c in p["invariantes"]))
        self.assertFalse((run / "FAILED.json").exists())
        # El resumen de terminal no trae valores de celdas de las tablas esperadas.
        printed = json.dumps(summary, ensure_ascii=False)
        for table in expected.get("tablas", {}).values():
            for value in {cell for row in table[1:] for cell in row if len(cell) > 2}:
                self.assertNotIn(value, printed)

    def check_recipe(self, name):
        expected = json.loads((ESPERADOS / f"{name}.json").read_text(encoding="utf-8"))
        inputs = [ROOT / expected["principal"], *(ROOT / p for p in expected["entradas"].values())]
        other = expected.get("otra_entrada")
        if other:
            inputs += [ROOT / other["principal"], *(ROOT / p for p in other["entradas"].values())]
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs + [ROOT / expected["receta"]]}
        summary, run = self.run_recipe(expected["receta"], expected, expected["principal"], expected["entradas"])
        self.check(expected, summary, run)
        if other:
            summary2, run2 = self.run_recipe(expected["receta"], other, other["principal"], other["entradas"])
            self.assertNotEqual(run, run2)
            self.check(other, summary2, run2)
        self.assertEqual({p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}, before)  # originales intactos

    def test_each_example_recipe_matches_its_handwritten_expected_results(self):
        self.assertTrue(RECETAS)
        for name in RECETAS:
            with self.subTest(receta=name):
                self.check_recipe(name)

    def test_every_example_recipe_has_expected_results_and_passes_comprobar(self):
        for name in RECETAS:
            with self.subTest(receta=name):
                self.assertTrue((ESPERADOS / f"{name}.json").is_file(), name)
                result = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), "comprobar",
                                         str(ROOT / "recetas" / f"{name}.json"), "--json"],
                                        cwd=ROOT, text=True, capture_output=True, encoding="utf-8")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["estado"], "valida")


if __name__ == "__main__":
    unittest.main()

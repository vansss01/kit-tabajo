"""Contrato para agentes (etapa 4): catálogo, comprobar, registro de códigos y estados."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kitlib import __version__, codigos
from kitlib.operations import ENRICH_CODES
from kitlib.runtime import configure
from test_esquemas import INVALID

configure()
SOURCES = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "src" / "kitlib").glob("*.py")}
ALL_SOURCE = "\n".join(SOURCES.values())


def kit(*args, expected=0):
    result = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), *map(str, args)], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == expected, (result.returncode, result.stdout[-2000:], result.stderr[-2000:])
    return result.stdout


class CodigosTests(unittest.TestCase):
    def emitted(self, patterns):
        return {m for pattern in patterns for m in re.findall(pattern, ALL_SOURCE)}

    def test_every_emitted_code_is_registered_and_every_registered_code_is_used(self):
        errors = self.emitted([r'error\("([a-z_]+)"', r'"codigo": "([a-z_]+)"(?!: )']) | {
            f"{kind}_no_admitidas" for kind in ("incidencias", "advertencias")}
        issues = self.emitted([r'issue\("([a-z_]+)"', r'codes\.append\("([a-z_]+)"\)', r'found\.append\("([a-z_]+)"\)',
                               r'return \("([a-z_]+)",\)']) | set(ENRICH_CODES.values())
        warnings = self.emitted([r'warnings?\.(?:append|add)\("([a-z_]+)"\)', r'"codigo": "([a-z_]+)",'])
        registry = codigos.ERRORES | codigos.INCIDENCIAS | codigos.ADVERTENCIAS
        self.assertEqual(sorted((errors | issues | warnings) - set(registry)), [])
        unused = [c for c in registry if f'"{c}"' not in ALL_SOURCE.replace(SOURCES["codigos.py"], "")
                  and not c.endswith("_no_admitidas")]
        self.assertEqual(unused, [])
        self.assertIn('f"{kind}_no_admitidas"', ALL_SOURCE)  # incidencias_ y advertencias_no_admitidas

    def test_manifest_states_are_registered(self):
        source = SOURCES["recetas.py"]
        run_states = set(re.findall(r'finish\("([a-z_]+)"', source)) | {"en_curso", "completada",
                                                                         "completada_con_incidencias"}
        step_states = set(re.findall(r'estado="([a-z_]+)"', source))  # current.update(estado=...)
        self.assertTrue(run_states <= set(codigos.ESTADOS_EJECUCION), run_states)
        self.assertTrue(step_states - {"detenida", "leida", "leida_con_incidencias"} <= set(codigos.ESTADOS_PASO),
                        step_states)
        motives = set(re.findall(r'finish\("fallida", 2, "([a-z_]+)"', source))
        self.assertEqual(motives, set(codigos.MOTIVOS_FALLO))


class CatalogoTests(unittest.TestCase):
    catalog: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(kit("catalogo"))

    def test_catalog_matches_the_real_cli(self):
        self.assertEqual(self.catalog["version_kit"], __version__)
        self.assertEqual(set(self.catalog["codigos_salida"]), {"0", "1", "2"})
        for command in self.catalog["comandos"]:  # cada comando listado existe de verdad
            self.assertIn("usage", kit(command, "--help"))
        self.assertIn("--numeric", [a["nombre"] for a in self.catalog["comandos"]["consultar"]["argumentos"]])
        # Escrito a mano desde el manual de ejecutar:
        self.assertEqual(self.catalog["operaciones_receta"]["completar"]["salidas"],
                         ["completadas", "sin_coincidencia", "ambiguas", "clave_vacia", "incidencias"])
        self.assertEqual(sorted(self.catalog["politicas"]["separar_en"]),
                         ["completar", "consolidar", "duplicados", "entradas", "validar"])
        self.assertEqual(self.catalog["esquemas"]["receta"]["archivo"], "schemas/receta.schema.json")
        self.assertTrue((ROOT / self.catalog["esquemas"]["receta"]["archivo"]).is_file())

    def test_codes_produced_by_invalid_recipes_are_in_the_catalog(self):
        listed = set(self.catalog["codigos"]["errores"])
        expected = {code for *_, code in INVALID if code}
        self.assertTrue(expected <= listed, expected - listed)


class ComprobarTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="comprobar-", dir=ROOT / "tmp")
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def write(self, name, content):
        path = self.folder / name
        path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        return path

    def check(self, path, *extra, expected=0):
        return json.loads(kit("comprobar", path, "--json", *extra, expected=expected))

    def test_valid_configs_without_running_or_writing_anything(self):
        def snapshot():
            return {d: sorted(p.name for p in (ROOT / d).iterdir()) if (ROOT / d).is_dir() else []
                    for d in ("results", "logs")}
        before = snapshot()
        for path, kind in ((ROOT / "recetas" / "revision_ordenes.json", "receta"), (ROOT / "examples" / "plan.json", "plan"),
                           (ROOT / "examples" / "reglas.json", "reglas")):
            result = self.check(path)
            self.assertEqual((result["estado"], result["tipo"], result["errores"]), ("valida", kind, []))
            self.assertIn("No se leyeron datos ni encabezados", result["alcance"])
        self.assertEqual(snapshot(), before)
        text = kit("comprobar", ROOT / "recetas" / "revision_ordenes.json")
        self.assertTrue(text.startswith("valida | receta | errores=0\nSolo configuración"))

    def test_comprobar_is_not_preview_nor_data_validation(self):
        # La receta es correcta; equipos.csv no tiene sus columnas. comprobar no lo ve (no lee encabezados)…
        recipe = ROOT / "recetas" / "revision_ordenes.json"
        self.assertEqual(self.check(recipe, "--principal", ROOT / "examples" / "equipos.csv")["estado"], "valida")
        # …la vista previa sí (lee encabezados), y validar con datos encuentra incidencias en las filas.
        kit("ejecutar", ROOT / "examples" / "equipos.csv", "--receta", recipe, "--vista-previa", "--json", expected=2)
        missing = self.check(recipe, "--principal", self.folder / "no existe.csv", expected=2)
        self.assertEqual(missing["errores"][0]["codigo"], "archivo_no_encontrado")

    def test_structured_errors_for_each_kind(self):
        plan = self.write("plan.json", {"steps": [{"op": "select", "columns": ["a"]},
                                                  {"op": "normalize", "columns": ["a"], "case": "title"}]})
        error = self.check(plan, expected=2)["errores"][0]
        self.assertEqual((error["codigo"], error["paso"], error["campo"]), ("configuracion_invalida", "plan paso 2",
                                                                            "steps[1]"))
        self.assertIn("case admite", error["mensaje"])
        self.assertTrue(error["sugerencia"])
        rules = self.write("reglas.json", {"columns": {"horas": {"type": "number", "min": "5", "max": "1"}}})
        self.assertIn("mínimo", self.check(rules, expected=2)["errores"][0]["mensaje"])
        recipe = self.write("receta.json", {"version": 1, "entradas": {"o": {}}, "pasos": [
            {"nombre": "perfil", "op": "inspeccionar", "entrada": "o"},
            {"nombre": "p", "op": "inspeccionar", "entrada": "perfil.resultado"}]})
        error = self.check(recipe, expected=2)["errores"][0]
        self.assertEqual((error["codigo"], error["paso"], error["campo"]), ("salida_inexistente", "p", "entrada"))
        repeated = self.write("rep.json", '{"columns": {"a": {}, "a": {}}}')
        self.assertEqual(self.check(repeated, expected=2)["errores"][0]["codigo"], "clave_json_repetida")
        unknown = self.write("x.json", '{"algo": 1}')
        self.assertEqual(self.check(unknown, expected=2)["errores"][0]["codigo"], "tipo_desconocido")
        forced = self.check(unknown, "--tipo", "reglas", expected=2)
        self.assertEqual((forced["tipo"], forced["errores"][0]["codigo"]), ("reglas", "configuracion_invalida"))
        self.assertEqual(self.check(self.write("roto.json", "{"), expected=2)["errores"][0]["codigo"], "json_invalido")


if __name__ == "__main__":
    unittest.main()

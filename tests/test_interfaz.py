"""Interfaz visual local (kitlib.interfaz): puente, servidor, estados, marcado de celdas y estáticos.

Los esperados están escritos a mano a partir de las entradas ficticias de examples/recetas/ (las notas de
examples/recetas/esperados/*.json describen fila por fila qué debe pasar). Ninguno se calcula con la
función que se prueba. Lo que necesita un navegador real (pintado, foco, arrastrar) no se prueba aquí.
"""
import base64
import csv
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kitlib.runtime import configure

configure()
from kitlib import codigos
from kitlib.interfaz import explicaciones
from kitlib.interfaz.puente import LIMITE_SUBIDA, TOPE_FILAS, Ocupado, PeticionInvalida, Puente
from kitlib.interfaz.servidor import ESTATICOS, Servidor

PRINCIPAL = {"revision_ordenes": "examples/recetas/ordenes_semana_1.csv",
             "consolidacion_turnos": "examples/recetas/turno_a.csv",
             "enriquecimiento_flota": "examples/recetas/ordenes_flota.csv"}
# Escritos a mano desde las notas de los esperados: (clave, valor) de cada contador y la frase.
CONTADORES = {
    "revision_ordenes": ([("entrada", 10), ("aceptadas", 3), ("rechazadas", 7)], "3 + 7 = 10. Ninguna fila se perdió"),
    "consolidacion_turnos": ([("entrada", 8), ("conservadas", 5), ("excluidas", 1), ("conflictos", 2)],
                             "5 + 1 + 2 = 8. Ninguna fila se perdió"),
    "enriquecimiento_flota": ([("entrada", 6), ("completadas", 3), ("sin_coincidencia", 1), ("ambiguas", 1),
                               ("clave_vacia", 1)], "3 + 1 + 1 + 1 = 6. Ninguna fila se perdió"),
}
PESTANAS = {
    "revision_ordenes": [("aceptadas", 3), ("rechazadas", 7), ("incidencias", 7), ("resumen", 1)],
    "consolidacion_turnos": [("conservadas", 5), ("excluidas", 1), ("conflictos", 2), ("incidencias", 2), ("resumen", 3)],
    "enriquecimiento_flota": [("completadas", 3), ("sin_coincidencia", 1), ("ambiguas", 1), ("clave_vacia", 1),
                              ("incidencias", 5), ("resumen", 2)],
}
EXCEL = {"revision_ordenes": "04-entrega/revision_ordenes.xlsx",
         "consolidacion_turnos": "05-entrega/consolidacion_turnos.xlsx",
         "enriquecimiento_flota": "03-entrega/enriquecimiento_flota.xlsx"}


def raiz_temporal(test):
    """Copia de examples/ y recetas/ dentro de tmp/, con data/ vacía: el puente trabaja ahí y no en el proyecto."""
    temp = tempfile.TemporaryDirectory(prefix="interfaz-", dir=ROOT / "tmp")
    test.addCleanup(temp.cleanup)
    root = Path(temp.name)
    shutil.copytree(ROOT / "examples", root / "examples")
    shutil.copytree(ROOT / "recetas", root / "recetas")
    (root / "data").mkdir()
    (root / "results").mkdir()
    return root


def escribir_receta(root, nombre, receta):
    path = root / "recetas" / f"{nombre}.json"
    path.write_text(json.dumps(receta, ensure_ascii=False), encoding="utf-8")
    return f"recetas/{nombre}.json"


def ejecutar(puente, archivo, receta):
    started = puente.iniciar_ejecucion(archivo, receta)
    puente.esperar(started["ejecucion"], 120)
    return puente.resultado(started["ejecucion"])


class EjecutorBloqueado:
    """Ejecutor falso: al ejecutar escribe un manifiesto «en_curso» (como el kit al empezar) y espera una señal."""

    def __init__(self, root):
        self.root, self.soltar, self.llamadas = root, threading.Event(), []

    def __call__(self, argumentos):
        self.llamadas.append(argumentos)
        if argumentos[0] == "ejecutar" and "--run-name" in argumentos:
            folder = ROOT / argumentos[argumentos.index("--output") + 1] / argumentos[argumentos.index("--run-name") + 1]
            folder.mkdir(parents=True)
            (folder / "manifiesto.json").write_text(json.dumps({"estado": "en_curso", "pasos": [], "entradas": {}}),
                                                    encoding="utf-8")
            self.soltar.wait(30)
        return 0, "{}"


# --------------------------------------------------------------------------- explicaciones

class ExplicacionesTests(unittest.TestCase):
    def test_every_catalog_code_has_an_entry_and_no_extra_ones(self):
        catalog = set(codigos.INCIDENCIAS) | set(codigos.ADVERTENCIAS)
        self.assertEqual(sorted(catalog - set(explicaciones.EXPLICACIONES)), [])
        self.assertEqual(sorted(set(explicaciones.EXPLICACIONES) - catalog), [])
        for code, (label, happened, todo) in explicaciones.EXPLICACIONES.items():
            self.assertTrue(label and happened and todo, code)
            self.assertLessEqual(len(label), 40, code)
            # Las plantillas solo admiten {columna}: ni valores ni otras variables.
            self.assertEqual(set(re.findall(r"\{(\w*)\}", happened + todo)) - {"columna"}, set(), code)

    def test_known_and_unknown_codes(self):
        self.assertEqual(explicaciones.explicar("campo_vacio", "equipo"), {
            "codigo": "campo_vacio", "etiqueta": "vacío", "conocido": True,
            "que_paso": "La celda de «equipo» está vacía y la regla exige un valor.",
            "que_hacer": "Complete el dato en el archivo original o confirme que puede quedar vacío."})
        unknown = explicaciones.explicar("codigo_nuevo_x", "c", "Mensaje del kit")
        self.assertEqual((unknown["etiqueta"], unknown["que_paso"], unknown["conocido"]),
                         ("codigo_nuevo_x", "Mensaje del kit", False))


# --------------------------------------------------------------------------- puente: rutas y subidas

class RutasTests(unittest.TestCase):
    def setUp(self):
        self.root = raiz_temporal(self)
        self.puente = Puente(self.root)

    def test_paths_outside_the_allowed_folders_are_rejected(self):
        (self.root / "secreto.csv").write_text("a\n1\n", encoding="utf-8")
        bad = ["../README.md", "examples/../secreto.csv", "/etc/passwd", str(self.root / "examples" / "plan.json"),
               "C:/Windows/win.ini", "secreto.csv", "src/kitlib/cli.py", "", "examples//x.csv", "tmp/x.csv"]
        for ruta in bad:
            with self.subTest(ruta=ruta), self.assertRaises(PeticionInvalida):
                self.puente.inspeccionar(ruta)
        with self.assertRaises(PeticionInvalida):
            self.puente.vista_previa("examples/recetas/ordenes_semana_1.csv", "examples/plan.json")  # receta fuera
        with self.assertRaises(PeticionInvalida):
            self.puente.iniciar_ejecucion("recetas/revision_ordenes.json", "recetas/revision_ordenes.json")

    def test_symlink_that_leaves_the_allowed_folders_is_rejected(self):
        outside = self.root / "fuera.csv"
        outside.write_text("a\n1\n", encoding="utf-8")
        try:
            os.symlink(outside, self.root / "data" / "enlace.csv")
        except (OSError, NotImplementedError):
            self.skipTest("Este sistema no permite crear enlaces simbólicos")
        with self.assertRaises(PeticionInvalida):
            self.puente.inspeccionar("data/enlace.csv")

    def test_file_list_has_only_readable_tables_and_skips_private_bitacora(self):
        (self.root / "data" / "bitacora").mkdir()
        (self.root / "data" / "bitacora" / "bitacora.csv").write_text("x\n", encoding="utf-8")
        (self.root / "data" / "propio.xlsx").write_bytes(b"")
        listed = {a["ruta"] for a in self.puente.archivos()}
        self.assertIn("data/propio.xlsx", listed)
        self.assertIn("examples/recetas/ordenes_semana_1.csv", listed)
        self.assertNotIn("data/bitacora/bitacora.csv", listed)
        self.assertNotIn("examples/plan.json", listed)  # JSON: no se distingue de un plan sin leerlo

    def test_upload_saves_a_copy_and_never_overwrites(self):
        content = base64.b64encode(b"a;b\n1;2\n").decode()
        first = self.puente.subir("mio.csv", content)
        second = self.puente.subir("mio.csv", base64.b64encode(b"otro\n").decode())
        self.assertEqual((first["ruta"], second["ruta"]), ("data/interfaz-subidas/mio.csv",
                                                           "data/interfaz-subidas/mio-2.csv"))
        self.assertTrue(second["renombrado"])
        self.assertIn("Tu archivo original no se tocó", first["aviso"])
        self.assertEqual((self.root / "data/interfaz-subidas/mio.csv").read_bytes(), b"a;b\n1;2\n")
        self.assertEqual((self.root / "data/interfaz-subidas/mio-2.csv").read_bytes(), b"otro\n")
        for name in ("../x.csv", "a/b.csv", "x.exe", ".oculto.csv", "x" * 120 + ".csv"):
            with self.subTest(name=name), self.assertRaises(PeticionInvalida):
                self.puente.subir(name, content)
        with self.assertRaises(PeticionInvalida):
            self.puente.subir("roto.csv", "no es base64!!")

    def test_upload_size_limit(self):
        self.assertEqual(LIMITE_SUBIDA, 20 * 1024 * 1024)  # documentado en docs/tools/interfaz.md
        too_big = base64.b64encode(b"a" * (LIMITE_SUBIDA + 1)).decode()
        with self.assertRaises(PeticionInvalida) as caught:
            self.puente.subir("grande.csv", too_big)
        self.assertEqual(caught.exception.http, 413)
        self.assertFalse((self.root / "data/interfaz-subidas/grande.csv").exists())

    def test_inspect_reports_the_kit_numbers_and_uses_the_kit_delimiter_hint(self):
        info = self.puente.inspeccionar("examples/recetas/ordenes_semana_1.csv")
        self.assertEqual(info["delimitador"], ";")  # el kit sugirió --delimiter ';'
        # Sin valores de celdas: el informe que deja inspeccionar no trae la muestra (--sample 0).
        reports = list((self.root / "tmp" / "interfaz").rglob("report.json"))
        self.assertEqual(len(reports), 2)  # primero con coma, luego con el delimitador sugerido
        for report in reports:
            text = report.read_text(encoding="utf-8")
            for value in ("OT100", "OT105", "03/11/2026", "abierta"):
                self.assertNotIn(value, text)
        self.assertEqual(info["tablas"], [{"hoja": None, "filas": 10, "alcance": "completo",
                                           "columnas": ["orden", "equipo", "fecha", "horas", "estado"]}])

    def test_recipes_titles_descriptions_and_extra_inputs(self):
        recipes = {r["archivo"]: r for r in self.puente.recetas()}
        self.assertEqual(sorted(recipes), ["consolidacion_turnos.json", "enriquecimiento_flota.json",
                                           "revision_ordenes.json"])
        flota = recipes["enriquecimiento_flota.json"]
        self.assertEqual(flota["titulo"], "enriquecimiento_flota")
        self.assertTrue(flota["descripcion"].startswith("Agrega modelo y área"))
        self.assertEqual(flota["otras_entradas"],
                         "Además del archivo principal, la receta usa: flota (../examples/recetas/flota.csv)")
        self.assertEqual(recipes["revision_ordenes.json"]["otras_entradas"], "")
        (self.root / "recetas" / "rota.json").write_text("{", encoding="utf-8")
        self.assertTrue(next(r for r in self.puente.recetas() if r["archivo"] == "rota.json")["error"])

    def test_one_run_at_a_time(self):
        fake = EjecutorBloqueado(self.root)
        puente = Puente(self.root, ejecutor=fake)
        first = puente.iniciar_ejecucion("examples/recetas/ordenes_semana_1.csv", "recetas/revision_ordenes.json")
        with self.assertRaises(Ocupado):
            puente.iniciar_ejecucion("examples/recetas/ordenes_semana_1.csv", "recetas/revision_ordenes.json")
        self.assertEqual(puente.resultado(first["ejecucion"])["franja"]["tipo"], "curso")
        fake.soltar.set()
        puente.esperar(first["ejecucion"])
        second = puente.iniciar_ejecucion("examples/recetas/ordenes_semana_1.csv", "recetas/revision_ordenes.json")
        puente.esperar(second["ejecucion"])
        self.assertEqual(len([c for c in fake.llamadas if c[0] == "ejecutar"]), 2)

    def test_open_folder_and_excel_only_inside_the_run(self):
        opened: list[Path] = []
        puente = Puente(self.root, abridor=opened.append)
        result = ejecutar(puente, PRINCIPAL["revision_ordenes"], "recetas/revision_ordenes.json")
        name = result["ejecucion"]
        puente.abrir(name)
        puente.abrir(name, result["pie"]["excel"])
        self.assertEqual(opened, [(self.root / "results" / name).resolve(),
                                  (self.root / "results" / name / "04-entrega/revision_ordenes.xlsx").resolve()])
        for bad in ("../../README.md", "/etc/passwd"):
            with self.subTest(bad=bad), self.assertRaises(PeticionInvalida):
                puente.abrir(name, bad)
        with self.assertRaises(PeticionInvalida):
            puente.abrir("../x")


# --------------------------------------------------------------------------- equivalencia con ./kit ejecutar

def _normal(manifest):
    return {"estado": manifest["estado"], "motivo": manifest["motivo"], "codigo_salida": manifest["codigo_salida"],
            "pasos": [{k: p.get(k) for k in ("nombre", "estado", "filas", "incidencias_por_codigo", "invariantes",
                                              "advertencias_por_codigo")} for p in manifest["pasos"]],
            "entradas": {n: {k: e.get(k) for k in ("filas_leidas", "filas_tabulares", "incidencias", "sha256")}
                         for n, e in manifest["entradas"].items()}}


class EquivalenciaTests(unittest.TestCase):
    results: dict = {}
    temp: tempfile.TemporaryDirectory
    root: Path

    @classmethod
    def setUpClass(cls):
        cls.results = {}
        cls.temp = tempfile.TemporaryDirectory(prefix="interfaz-eq-", dir=ROOT / "tmp")
        root = Path(cls.temp.name)
        shutil.copytree(ROOT / "examples", root / "examples")
        shutil.copytree(ROOT / "recetas", root / "recetas")
        (root / "data").mkdir()
        cls.root = root
        puente = Puente(root)
        for name, principal in PRINCIPAL.items():
            ui = ejecutar(puente, principal, f"recetas/{name}.json")
            cli = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), "ejecutar", str(root / principal),
                                  "--receta", str(root / "recetas" / f"{name}.json"), "--output",
                                  str(root / "cli"), "--json"], cwd=ROOT, capture_output=True, text=True,
                                 encoding="utf-8")
            cls.results[name] = (ui, json.loads(cli.stdout), cli.returncode)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def manifest(self, run):
        return json.loads((Path(run) / "manifiesto.json").read_text(encoding="utf-8"))

    def test_interface_and_cli_give_the_same_manifest(self):
        for name, (ui, cli, code) in self.results.items():
            with self.subTest(receta=name):
                ui_manifest = self.manifest(self.root / ui["pie"]["carpeta"])
                self.assertEqual(_normal(ui_manifest), _normal(self.manifest(cli["ruta_resultados"])))
                self.assertEqual((ui["estado"], ui["codigo_salida"]), (cli["estado"], code))

    def test_interface_json_matches_manifest_and_handwritten_expected(self):
        for name, (ui, _, _) in self.results.items():
            with self.subTest(receta=name):
                expected = json.loads((ROOT / "examples/recetas/esperados" / f"{name}.json").read_text(encoding="utf-8"))
                self.assertEqual(ui["estado"], expected["estado"])
                self.assertEqual(ui["franja"]["tipo"], "incidencias")
                self.assertEqual(ui["franja"]["titulo"], "Completada con incidencias")
                counters, phrase = CONTADORES[name]
                self.assertEqual([(c["clave"], c["valor"]) for c in ui["contadores"]], counters)
                self.assertEqual(ui["conservacion"]["frase"], phrase)
                self.assertTrue(ui["conservacion"]["mostrar"])
                self.assertEqual([(t["id"], t["conteo"]) for t in ui["pestanas"]], PESTANAS[name])
                self.assertEqual(ui["pie"]["excel"], EXCEL[name])
                self.assertTrue(ui["pie"]["original_sin_cambios"])
                self.assertEqual(ui["pie"]["frase_original"], "Tu archivo original no se modificó")
                # Las cifras de las pestañas son las del manifiesto (no contadas por la interfaz).
                manifest = self.manifest(self.root / ui["pie"]["carpeta"])
                outputs = {o: i["filas"] for p in manifest["pasos"] if p["op"] != "exportar"
                           for o, i in p.get("salidas", {}).items()}
                for tab in ui["pestanas"]:
                    if tab["id"] not in ("incidencias", "resumen"):
                        self.assertEqual(tab["conteo"], outputs[tab["id"]], tab["id"])

    def test_marked_cells_match_incidencias_csv(self):
        ui = self.results["revision_ordenes"][0]
        run = self.root / ui["pie"]["carpeta"]
        with (run / "02-revision" / "incidencias.csv").open(encoding="utf-8", newline="") as stream:
            from_csv = {(r["fila"], r["columna"], r["codigo"]) for r in csv.DictReader(stream, delimiter=";")}
        rejected = next(t for t in ui["pestanas"] if t["id"] == "rechazadas")
        marked = {(f["fila_original"], c, m["codigo"]) for f in rejected["filas"] for c in f["marcadas"]
                  for m in f["motivos"] if m["columna"] == c}
        self.assertEqual(marked, from_csv)
        # Escrito a mano (nota de esperados/revision_ordenes.json): fila original → columna culpable.
        self.assertEqual([(f["fila_original"], f["marcadas"]) for f in rejected["filas"]],
                         [("4", ["orden"]), ("5", ["fecha"]), ("6", ["equipo"]), ("7", ["horas"]), ("8", ["horas"]),
                          ("9", ["orden"]), ("10", ["horas"])])
        self.assertEqual(rejected["filas"][1]["celdas"]["fecha"], "03/11/2026")
        self.assertEqual(rejected["filas"][1]["motivos"][0]["etiqueta"], "tipo o fecha inválida")
        accepted = next(t for t in ui["pestanas"] if t["id"] == "aceptadas")
        self.assertEqual([f["marcadas"] for f in accepted["filas"]], [[], [], []])
        self.assertEqual([f["fila_original"] for f in accepted["filas"]], ["2", "3", "11"])

    def test_marked_cells_in_enrichment_and_duplicates(self):
        flota = self.results["enriquecimiento_flota"][0]
        tabs = {t["id"]: t for t in flota["pestanas"]}
        self.assertEqual([(f["fila_original"], f["marcadas"], [m["codigo"] for m in f["motivos"]])
                          for k in ("sin_coincidencia", "ambiguas", "clave_vacia") for f in tabs[k]["filas"]],
                         [("4", ["equipo"], ["clave_sin_coincidencia"]), ("5", ["equipo"], ["coincidencia_ambigua"]),
                          ("6", ["equipo"], ["clave_vacia"])])
        turnos = {t["id"]: t for t in self.results["consolidacion_turnos"][0]["pestanas"]}
        self.assertEqual([(f["entrada"], f["fila_original"], f["marcadas"]) for f in turnos["conflictos"]["filas"]],
                         [("turno_a", "5", ["orden"]), ("turno_b", "3", ["orden"])])
        incid = {g["codigo"]: (g["cantidad"], g["columnas"]) for g in turnos["incidencias"]["grupos"]}
        self.assertEqual(incid, {"conflicto_de_duplicados": (2, ["orden"])})


# --------------------------------------------------------------------------- estados de la franja

class EstadosTests(unittest.TestCase):
    def setUp(self):
        self.root = raiz_temporal(self)
        self.puente = Puente(self.root)

    def test_no_runs_yet(self):
        result = self.puente.resultado()
        self.assertEqual((result["estado"], result["franja"]["titulo"]), ("sin_ejecuciones", "Sin ejecuciones todavía"))
        self.assertEqual((result["contadores"], result["pestanas"], result["conservacion"]["mostrar"]), ([], [], False))

    def test_completed_without_issues(self):
        result = ejecutar(self.puente, "examples/recetas/ordenes_semana_2.csv", "recetas/revision_ordenes.json")
        self.assertEqual((result["estado"], result["franja"]["tipo"], result["franja"]["titulo"]),
                         ("completada", "exito", "Completada"))
        self.assertEqual([(c["clave"], c["valor"]) for c in result["contadores"]],
                         [("entrada", 5), ("aceptadas", 5), ("rechazadas", 0)])
        self.assertEqual(result["conservacion"]["frase"], "5 + 0 = 5. Ninguna fila se perdió")

    def test_stopped_by_policy(self):
        recipe = json.loads((self.root / "recetas" / "revision_ordenes.json").read_text(encoding="utf-8"))
        del recipe["pasos"][1]["politica"]  # sin política: detener
        receta = escribir_receta(self.root, "sin_politica", recipe)
        result = ejecutar(self.puente, PRINCIPAL["revision_ordenes"], receta)
        self.assertEqual((result["estado"], result["motivo"], result["franja"]["tipo"]),
                         ("fallida", "detenida_por_politica", "fallo"))
        self.assertEqual(result["franja"]["titulo"], "Detenida por la política de la receta")
        error = result["franja"]["errores"][0]
        self.assertEqual((error["codigo"], error["paso"], error["campo"]), ("incidencias_no_admitidas", "revision", "politica"))
        self.assertTrue(error["sugerencia"])
        self.assertEqual(result["contadores"], [])  # el paso detenido no publicó tablas
        self.assertFalse(result["conservacion"]["mostrar"])
        self.assertFalse(result["pie"]["original_sin_cambios"])  # sin audit.json no se afirma
        self.assertIsNone(result["pie"]["excel"])

    def test_excel_button_only_when_the_run_wrote_an_xlsx(self):
        recipe = json.loads((self.root / "recetas" / "revision_ordenes.json").read_text(encoding="utf-8"))
        recipe["pasos"][3]["formatos"] = ["csv"]
        result = ejecutar(self.puente, PRINCIPAL["revision_ordenes"], escribir_receta(self.root, "solo_csv", recipe))
        self.assertEqual(result["estado"], "completada_con_incidencias")
        self.assertIsNone(result["pie"]["excel"])
        self.assertTrue(result["pie"]["original_sin_cambios"])
        self.assertEqual(result["pie"]["carpeta"], "results/" + result["ejecucion"])

    def test_execution_error(self):
        receta = escribir_receta(self.root, "conversion", {
            "version": 1, "nombre": "conversion", "entradas": {"ordenes": {"principal": True, "delimiter": ";"}},
            "pasos": [{"nombre": "convertir", "op": "transformar", "entrada": "ordenes",
                       "plan": {"steps": [{"op": "convert", "column": "orden", "type": "number"}]}}]})
        result = ejecutar(self.puente, PRINCIPAL["revision_ordenes"], receta)
        self.assertEqual((result["estado"], result["motivo"]), ("fallida", "error_de_ejecucion"))
        self.assertEqual(result["franja"]["titulo"], "Fallida por un error de ejecución")
        self.assertEqual(result["franja"]["errores"][0]["paso"], "convertir")

    def test_invalid_recipe_lists_code_step_field_and_hint(self):
        receta = escribir_receta(self.root, "mala", {"version": 1})
        result = ejecutar(self.puente, PRINCIPAL["revision_ordenes"], receta)
        self.assertEqual((result["estado"], result["franja"]["tipo"]), ("error", "fallo"))
        self.assertEqual(result["franja"]["titulo"], "Receta inválida: no se ejecutó nada")
        codes = [(e["codigo"], e["campo"]) for e in result["franja"]["errores"]]
        self.assertEqual(codes, [("entradas_ausentes", "entradas"), ("principal_ambigua", "entradas"),
                                 ("pasos_ausentes", "pasos")])
        self.assertIn("sugerencia", result["franja"]["errores"][0])

    def test_running_then_cut_and_interrupted(self):
        fake = EjecutorBloqueado(self.root)
        puente = Puente(self.root, ejecutor=fake)
        started = puente.iniciar_ejecucion(PRINCIPAL["revision_ordenes"], "recetas/revision_ordenes.json")
        running = puente.resultado(started["ejecucion"])
        self.assertEqual((running["estado"], running["franja"]["tipo"], running["franja"]["titulo"]),
                         ("en_curso", "curso", "Ejecutando…"))
        self.assertTrue(puente.estado()["ejecutando"])
        fake.soltar.set()
        puente.esperar(started["ejecucion"])
        cut = puente.resultado(started["ejecucion"])  # manifiesto en_curso y nada en marcha: cortada de golpe
        self.assertEqual((cut["estado"], cut["franja"]["tipo"], cut["franja"]["titulo"]),
                         ("en_curso", "fallo", "Ejecución cortada de golpe"))
        # Interrumpida (Ctrl+C): manifiesto tal como lo deja recetas.py al recibir KeyboardInterrupt.
        folder = self.root / "results" / "interrumpida1"
        folder.mkdir()
        (folder / "manifiesto.json").write_text(json.dumps({
            "estado": "fallida", "motivo": "interrumpida", "codigo_salida": 2, "error": None, "entradas": {},
            "pasos": [{"numero": 1, "nombre": "revision", "op": "validar", "carpeta": "01-revision",
                       "estado": "interrumpido"}]}), encoding="utf-8")
        stopped = Puente(self.root).resultado("interrumpida1")
        self.assertEqual((stopped["franja"]["tipo"], stopped["franja"]["titulo"]),
                         ("fallo", "Interrumpida antes de terminar"))

    def test_conservation_hidden_when_the_invariant_is_not_recorded_as_met(self):
        result = ejecutar(self.puente, PRINCIPAL["revision_ordenes"], "recetas/revision_ordenes.json")
        folder = self.root / result["pie"]["carpeta"]
        manifest = json.loads((folder / "manifiesto.json").read_text(encoding="utf-8"))
        manifest["pasos"][1]["invariantes"][0]["cumple"] = False
        (folder / "manifiesto.json").write_text(json.dumps(manifest), encoding="utf-8")
        again = Puente(self.root).resultado(result["ejecucion"])
        self.assertFalse(again["conservacion"]["mostrar"])
        self.assertNotIn("frase", again["conservacion"])
        (folder / "audit.json").write_text(json.dumps({"originales_sha256_sin_cambios": False}), encoding="utf-8")
        self.assertFalse(Puente(self.root).resultado(result["ejecucion"])["pie"]["original_sin_cambios"])

    def test_row_cap_with_notice(self):
        rows = ["orden;equipo;fecha;horas;estado"] + [f"OT{n:04d};0007;2026-11-0{1 + n % 9};1,0;abierta"
                                                       for n in range(TOPE_FILAS + 30)]
        (self.root / "data" / "largo.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
        result = ejecutar(self.puente, "data/largo.csv", "recetas/revision_ordenes.json")
        accepted = next(t for t in result["pestanas"] if t["id"] == "aceptadas")
        self.assertEqual((accepted["total"], accepted["mostradas"]), (230, 200))
        self.assertTrue(accepted["aviso_tope"].startswith("Mostrando 200 de 230."))
        self.assertIn("02-revision/aceptadas.csv", accepted["aviso_tope"])

    def test_preview_uses_the_kit_preview(self):
        preview = self.puente.vista_previa(PRINCIPAL["revision_ordenes"], "recetas/revision_ordenes.json")
        self.assertEqual(preview["estado"], "vista_previa")
        self.assertTrue(preview["alcance"].startswith("Vista previa: se comprobó la receta"))
        self.assertIn("NO se leyeron", preview["alcance"])
        self.assertEqual([p["nombre"] for p in preview["pasos"]], ["perfil", "revision", "resumen", "entrega"])
        self.assertFalse((self.root / "results").exists() and any((self.root / "results").iterdir()))


# --------------------------------------------------------------------------- servidor HTTP

class ServidorTests(unittest.TestCase):
    def setUp(self):
        self.root = raiz_temporal(self)
        self.servidor = Servidor(Puente(self.root), puerto=0).servir_en_hilo()
        self.addCleanup(self.servidor.cerrar)
        self.host = f"127.0.0.1:{self.servidor.puerto}"

    def pedir(self, metodo, ruta, cuerpo=None, token: bool | str | None = True, host=None, tipo="application/json"):
        conn = http.client.HTTPConnection("127.0.0.1", self.servidor.puerto, timeout=60)
        headers = {"Host": host or self.host}
        if token is True:
            headers["X-Kit-Token"] = self.servidor.token
        elif token:
            headers["X-Kit-Token"] = token
        data = None
        if cuerpo is not None:
            data = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode()
            headers["Content-Type"] = tipo
        conn.request(metodo, ruta, body=data, headers=headers)
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response.status, dict(response.getheaders()), body

    def json(self, *args, **kwargs):
        status, _, body = self.pedir(*args, **kwargs)
        return status, json.loads(body)

    def test_listens_on_a_free_port_of_127_0_0_1(self):
        self.assertEqual(self.servidor.httpd.server_address[0], "127.0.0.1")
        self.assertGreater(self.servidor.puerto, 0)
        self.assertTrue(self.servidor.url.startswith(f"http://127.0.0.1:{self.servidor.puerto}/?token="))
        other = Servidor(Puente(self.root), puerto=0)
        self.addCleanup(other.cerrar)
        self.assertNotEqual(other.puerto, self.servidor.puerto)
        self.assertNotEqual(other.token, self.servidor.token)

    def test_every_endpoint(self):
        status, page_headers, page = self.pedir("GET", f"/?token={self.servidor.token}", token=None)
        self.assertEqual(status, 200)
        self.assertIn(self.servidor.token.encode(), page)
        self.assertIn(b"KIT TABAJO", page)
        self.assertIn("default-src 'none'", page_headers["Content-Security-Policy"])
        for name in ("interfaz.css", "interfaz.js"):
            status, _, body = self.pedir("GET", "/estaticos/" + name)
            self.assertEqual((status, body), (200, (ESTATICOS / name).read_bytes()))
        status, info = self.json("GET", "/api/estado")
        self.assertEqual((status, info["ejecutando"], info["limites"]["tope_filas"]), (200, False, 200))
        status, files = self.json("GET", "/api/archivos")
        self.assertIn("examples/recetas/ordenes_semana_1.csv", [a["ruta"] for a in files["archivos"]])
        status, info = self.json("GET", "/api/inspeccionar?ruta=examples/recetas/ordenes_semana_1.csv")
        self.assertEqual((status, info["tablas"][0]["filas"]), (200, 10))
        status, recipes = self.json("GET", "/api/recetas")
        self.assertEqual(len(recipes["recetas"]), 3)
        status, preview = self.json("GET", "/api/vista_previa?archivo=examples/recetas/ordenes_semana_1.csv"
                                           "&receta=recetas/revision_ordenes.json")
        self.assertEqual((status, preview["estado"]), (200, "vista_previa"))
        status, empty = self.json("GET", "/api/resultado")
        self.assertEqual((status, empty["estado"]), (200, "sin_ejecuciones"))
        status, up = self.json("POST", "/api/subir", {"nombre": "s.csv", "contenido_base64": base64.b64encode(b"a\n1\n").decode()})
        self.assertEqual((status, up["ruta"]), (201, "data/interfaz-subidas/s.csv"))
        status, started = self.json("POST", "/api/ejecutar", {"archivo": "examples/recetas/ordenes_semana_1.csv",
                                                              "receta": "recetas/revision_ordenes.json"})
        self.assertEqual(status, 202)
        self.servidor.puente.esperar(started["ejecucion"], 120)
        status, result = self.json("GET", "/api/resultado?ejecucion=" + started["ejecucion"])
        self.assertEqual((status, result["estado"]), (200, "completada_con_incidencias"))
        status, _ = self.json("POST", "/api/abrir", {"ejecucion": started["ejecucion"], "archivo": "../../x"})
        self.assertEqual(status, 400)
        self.assertEqual(self.json("GET", "/api/nada")[0], 404)

    def test_missing_or_wrong_token(self):
        for token in (None, "", "otro-token", self.servidor.token[:-1]):
            with self.subTest(token=token):
                status, body = self.json("GET", "/api/estado", token=token)
                self.assertEqual((status, body["codigo"]), (403, "token_invalido"))
                self.assertEqual(self.pedir("GET", "/", token=token)[0], 403)
                self.assertEqual(self.pedir("GET", "/estaticos/interfaz.js", token=token)[0], 403)
                status, _ = self.json("POST", "/api/ejecutar", {"archivo": "x", "receta": "y"}, token=token)
                self.assertEqual(status, 403)
        self.assertFalse((self.root / "results").exists() and any((self.root / "results").iterdir()))

    def test_wrong_host(self):
        port = self.servidor.puerto
        for host in ("evil.example", f"evil.example:{port}", "127.0.0.1", f"127.0.0.1:{port + 1}",
                     f"localhost.evil:{port}", f"192.168.0.1:{port}"):
            with self.subTest(host=host):
                status, body = self.json("GET", "/api/estado", host=host)
                self.assertEqual((status, body["codigo"]), (400, "host_no_permitido"))
        self.assertEqual(self.pedir("GET", "/api/estado", host=f"localhost:{port}")[0], 200)

    def test_no_permissive_cors_and_post_only_with_json(self):
        _, headers, _ = self.pedir("GET", "/api/estado")
        self.assertFalse([h for h in headers if h.lower().startswith("access-control")])
        status, _, _ = self.pedir("OPTIONS", "/api/ejecutar")
        self.assertNotEqual(status, 200)
        self.assertEqual(self.json("GET", "/api/ejecutar?archivo=x&receta=y")[0], 405)
        self.assertEqual(self.json("GET", "/api/subir")[0], 405)
        self.assertEqual(self.json("GET", "/api/abrir")[0], 405)
        status, _ = self.json("POST", "/api/ejecutar", b"archivo=x&receta=y", tipo="application/x-www-form-urlencoded")
        self.assertEqual(status, 400)
        status, _ = self.json("POST", "/api/ejecutar", b"[1]")
        self.assertEqual(status, 400)
        # JSON válido pero sin Content-Type JSON (lo que otra página podría enviar sin permiso previo): rechazado.
        valid = json.dumps({"archivo": "examples/recetas/ordenes_semana_1.csv",
                            "receta": "recetas/revision_ordenes.json"}).encode()
        for kind in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data"):
            with self.subTest(tipo=kind):
                self.assertEqual(self.json("POST", "/api/ejecutar", valid, tipo=kind)[0], 400)
        self.assertFalse((self.root / "results").exists() and any((self.root / "results").iterdir()))
        self.assertEqual(self.json("PUT", "/api/ejecutar", {})[0], 405)

    def test_routes_outside_allowed_folders_over_http(self):
        for query in ("ruta=../README.md", "ruta=/etc/passwd", "ruta=src/kitlib/cli.py", "ruta=examples/../kit.py"):
            with self.subTest(query=query):
                self.assertEqual(self.json("GET", "/api/inspeccionar?" + query)[0], 400)
        self.assertEqual(self.pedir("GET", "/estaticos/../puente.py")[0], 404)
        self.assertEqual(self.pedir("GET", "/estaticos/puente.py")[0], 404)

    def test_second_simultaneous_run_is_rejected(self):
        fake = EjecutorBloqueado(self.root)
        self.servidor.puente.ejecutor = fake
        body = {"archivo": "examples/recetas/ordenes_semana_1.csv", "receta": "recetas/revision_ordenes.json"}
        status, first = self.json("POST", "/api/ejecutar", body)
        self.assertEqual(status, 202)
        status, second = self.json("POST", "/api/ejecutar", body)
        self.assertEqual((status, second["codigo"]), (409, "ocupado"))
        fake.soltar.set()
        self.servidor.puente.esperar(first["ejecucion"])

    def test_upload_over_http_does_not_overwrite(self):
        (self.root / "data" / "interfaz-subidas").mkdir(parents=True)
        (self.root / "data" / "interfaz-subidas" / "x.csv").write_bytes(b"original\n")
        status, up = self.json("POST", "/api/subir", {"nombre": "x.csv", "contenido_base64": base64.b64encode(b"nuevo\n").decode()})
        self.assertEqual((status, up["nombre"]), (201, "x-2.csv"))
        self.assertEqual((self.root / "data" / "interfaz-subidas" / "x.csv").read_bytes(), b"original\n")


# --------------------------------------------------------------------------- estáticos y núcleo

class EstaticosTests(unittest.TestCase):
    def test_no_external_references(self):
        for path in sorted(ESTATICOS.iterdir()):
            text = path.read_text(encoding="utf-8")
            with self.subTest(archivo=path.name):
                self.assertEqual(re.findall(r"(?i)https?://", text), [])
                self.assertEqual(re.findall(r"(?i)(?:src|href)\s*=\s*[\"']//", text), [])
                self.assertNotIn("@import", text)
                self.assertNotIn("url(", text.replace("url(data:", ""))

    def test_visual_tokens_of_the_specification(self):
        css = (ESTATICOS / "interfaz.css").read_text(encoding="utf-8")
        for token in ("#F5F5F7", "#FFFFFF", "#E2E2E7", "#1D1D1F", "#636368", "#EFEFF2", "#0066CC", "#1E7B34",
                      "#C4302B", "#9A5B00", "#FFF7E6", "#F0DDB5", "#E9E9ED", "#B3261E", "#FDECEA", "#D2D2D7",
                      'system-ui, -apple-system, "Segoe UI", sans-serif', "font-size: 15px", "height: 44px",
                      "height: 48px", "height: 6px", "font-size: 30px", "font-size: 11px", "tabular-nums",
                      "grid-template-columns: 280px", ":focus-visible", "overflow-x: hidden"):
            self.assertIn(token, css)
        html = (ESTATICOS / "interfaz.html").read_text(encoding="utf-8")
        for text in ("KIT TABAJO", "Todo local · tus archivos no salen de este equipo", ">Archivo<", ">Receta<",
                     ">Ejecutar<", "Vista previa", "Abrir carpeta", "Exportar a Excel"):
            self.assertIn(text, html)
        self.assertEqual(html.count("<button"), 4)


class NucleoTests(unittest.TestCase):
    def test_core_does_not_import_the_interface(self):
        code = ("import sys; sys.path.insert(0, 'src'); from kitlib.runtime import configure; configure(); "
                "from kitlib import cli; cli.main(['catalogo']); "
                "assert not [m for m in sys.modules if m.startswith('kitlib.interfaz')], 'importada'")
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, capture_output=True, text=True,
                                encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        for path in (ROOT / "src" / "kitlib").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            imports = re.findall(r"^\s*(?:from|import) kitlib\.interfaz.*$", text, flags=re.M)
            self.assertEqual(imports, [] if path.name != "cli.py" else ["            from kitlib.interfaz import servidor"],
                             path.name)

    def test_interfaz_command_help(self):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), "interfaz", "--help"], capture_output=True,
                                text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0)
        for text in ("usage:", "--puerto", "--sin-abrir", "127.0.0.1", "Ctrl+C"):
            self.assertIn(text, result.stdout)


class SalidaSinCambiosTests(unittest.TestCase):
    """La salida por defecto (texto y --json) de los comandos existentes es idéntica a la de 1.5.1 (commit
    ffee2ac), con la misma entrada y el mismo --run-name. Necesita el historial de Git: en un clon superficial
    se omite; la CI descarga el historial completo (fetch-depth: 0). Diferencias declaradas y excluidas: `--help` general y `catalogo` listan el
    comando nuevo `interfaz`, `--version` y `catalogo` dicen la versión nueva, y el error de comando
    desconocido añade `interfaz` a la lista de comandos válidos (comprobado abajo como única diferencia)."""
    COMMIT = "ffee2ac"
    COMMANDS = [
        ["inspeccionar", "examples/equipos.csv", "--delimiter", ";", "--sample", "2"],
        ["validar", "examples/con incidencias.csv", "--delimiter", ";", "--rules", "examples/reglas.json"],
        ["comparar", "examples/anterior.csv", "examples/entradas/turno A.csv", "--delimiter", ";", "--key", "orden"],
        ["consolidar", "examples/entradas", "--delimiter", ";"],
        ["transformar", "examples/entradas/turno A.csv", "--delimiter", ";", "--decimal", ",", "--plan",
         "examples/plan.json"],
        ["exportar", "examples/con incidencias.csv", "--delimiter", ";", "--rules", "examples/reglas.json"],
        ["consultar", "examples/equipos.csv", "--delimiter", ";", "--sql", "SELECT * FROM t"],
        ["ejecutar", "examples/recetas/ordenes_semana_1.csv", "--receta", "recetas/revision_ordenes.json"],
        ["ejecutar", "examples/recetas/ordenes_semana_1.csv", "--receta", "recetas/revision_ordenes.json",
         "--vista-previa"],
        ["comprobar", "recetas/consolidacion_turnos.json"],
        ["inspeccionar"], ["comando_que_no_existe"],
    ]

    def test_default_output_identical_to_1_5_1(self):
        probe = subprocess.run(["git", "cat-file", "-e", self.COMMIT + "^{commit}"], cwd=ROOT, capture_output=True)
        if probe.returncode:
            self.skipTest("Historial de Git no disponible (clon superficial): no se puede extraer 1.5.1")
        temp = tempfile.TemporaryDirectory(prefix="compat-1.5.1-", dir=ROOT / "tmp")
        self.addCleanup(temp.cleanup)
        old, new = Path(temp.name) / "antes", Path(temp.name) / "ahora"
        archive = subprocess.run(["git", "archive", "--format=tar", self.COMMIT, "src", "kit.py", "examples",
                                  "recetas", "schemas"], cwd=ROOT, capture_output=True, check=True).stdout
        import io
        import tarfile
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(old, filter="data")
        new.mkdir()
        shutil.copytree(ROOT / "src", new / "src", ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("examples", "recetas", "schemas"):
            shutil.copytree(old / name, new / name)  # mismas entradas en los dos árboles
        shutil.copy2(ROOT / "kit.py", new / "kit.py")
        for n, command in enumerate(self.COMMANDS):
            for extra in ([], ["--json"]):
                line = [*command, *(["--run-name", f"c{n}"] if command[0] in ("inspeccionar", "validar", "comparar",
                        "consolidar", "transformar", "exportar", "consultar", "ejecutar") and len(command) > 1
                        and "--vista-previa" not in command else []), *extra]
                with self.subTest(comando=" ".join(line)):
                    outputs = []
                    for tree in (old, new):
                        result = subprocess.run([sys.executable, "-B", str(tree / "kit.py"), *line], cwd=tree,
                                                capture_output=True, text=True, encoding="utf-8")
                        text = (result.stdout + "\n--stderr--\n" + result.stderr).replace(str(tree), "<RAIZ>")
                        text = text.replace(str(tree).replace("\\", "/"), "<RAIZ>")
                        text = text.replace(json.dumps(str(tree))[1:-1], "<RAIZ>")  # rutas escapadas en JSON (Windows)
                        outputs.append((result.returncode, text))
                    if command == ["comando_que_no_existe"]:
                        # Única diferencia admitida: la lista de comandos válidos nombra también `interfaz`.
                        self.assertNotEqual(outputs[0], outputs[1])
                        fixed = (outputs[1][1].replace(",interfaz}", "}").replace(", interfaz.", ".")
                                 .replace(", 'interfaz')", ")"))
                        self.assertEqual(outputs[0], (outputs[1][0], fixed))
                        continue
                    self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()

"""consultar (etapa 4): tipos explícitos por tabla y columna y detector de texto numérico con coste acotado.
Resultados esperados calculados a mano en los comentarios."""
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
# t: medidas con coma decimal. f: "horas" es un código de 3 dígitos con ceros (mismo nombre, otra cosa).
# JOIN por equipo: OT1 (0007 ↔ 010) y OT2 (0010 ↔ 009); OT3 (0009) no está en f.
# SUM(t.horas) = 2,5 + 3,5 = 6; como texto SQLite suma 2 + 3 = 5. MAX(f.horas) como texto = "010".
ORDENES = "orden;equipo;horas\nOT1;0007;2,5\nOT2;0010;3,5\nOT3;0009;10,0\n"
FLOTA = "equipo;horas\n0007;010\n0010;009\n"
SQL = "SELECT SUM(t.horas) AS total, MAX(f.horas) AS mayor FROM t JOIN f ON f.equipo = t.equipo"


class SqlTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="sql-", dir=ROOT / "tmp")
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.ordenes = self.write("ordenes.csv", ORDENES)
        self.flota = self.write("flota.csv", FLOTA)

    def write(self, name, content):
        path = self.folder / name
        path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        return path

    def query(self, *extra, sql=SQL, source=None, expected=0):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), "consultar", str(source or self.ordenes),
                                 "--delimiter", ";", "--decimal", ",", "--tabla", f"f={self.flota}", "--sql", sql,
                                 "--output", str(self.folder / "out"), "--json", *map(str, extra)],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_explicit_types_per_table_in_a_join(self):
        typed = self.query("--tipo", "t.horas=number")
        self.assertEqual(typed["resultado"]["filas"], [{"total": "6", "mayor": "010"}])  # f.horas sigue siendo código
        self.assertNotIn("advertencias_por_codigo", typed)
        everywhere = self.query("--numeric", "horas")  # --numeric de siempre: todas las tablas con esa columna
        self.assertEqual(everywhere["resultado"]["filas"], [{"total": "6", "mayor": "10"}])  # "010" pasó a 10
        explicit_text = self.query("--tipo", "t.horas=number", "--tipo", "f.horas=string")
        self.assertEqual(explicit_text["resultado"]["filas"], [{"total": "6", "mayor": "010"}])

    def test_comma_decimal_case_warns_or_is_covered_by_types(self):
        source = self.write("v.csv", "v\n2,5\n3,5\n")
        total = "SELECT SUM(v) AS total FROM t"
        warned = self.query(sql=total, source=source, expected=1)
        self.assertEqual((warned["resultado"]["filas"], warned["advertencias_por_codigo"]),
                         ([{"total": "5"}], {"resultado_depende_de_texto_sin_numeric": 1}))
        self.assertEqual(self.query("--tipo", "t.v=number", sql=total, source=source)["resultado"]["filas"],
                         [{"total": "6"}])
        # Declararla texto a propósito: se respeta (SQLite suma 2 + 3) y no se avisa.
        self.assertEqual(self.query("--tipo", "t.v=string", sql=total, source=source)["resultado"]["filas"],
                         [{"total": "5"}])

    def test_detector_cost_limit_and_switch(self):
        # t y f suman 5 filas: con límite 5 el detector se ejecuta; con 4 no, y se avisa que no se hizo.
        ran = self.query("--detector-max-filas", "5", expected=1)
        self.assertEqual(ran["advertencias_por_codigo"], {"resultado_depende_de_texto_sin_numeric": 1})
        skipped = self.query("--detector-max-filas", "4", expected=1)
        self.assertEqual(skipped["advertencias_por_codigo"], {"detector_texto_numerico_omitido": 1})
        self.assertEqual(skipped["resultado"]["filas"], [{"total": "5", "mayor": "010"}])
        report = json.loads((Path(skipped["ruta_resultados"]) / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["advertencias_detalle"][0]["filas"], 5)
        off = self.query("--detector-texto-numerico", "no")
        self.assertEqual((off["codigo_salida"], off["resultado"]["filas"]), (0, [{"total": "5", "mayor": "010"}]))
        # Con todas las columnas usadas ya tipadas no hay nada que detectar, aunque el límite sea mínimo.
        self.assertEqual(self.query("--tipo", "t.horas=number", "--detector-max-filas", "1")["codigo_salida"], 0)

    def test_invalid_type_declarations(self):
        for args, field in ((("--tipo", "t.horas"), "--tipo"), (("--tipo", "horas=number"), "--tipo"),
                            (("--tipo", "t.horas=decimal"), "--tipo"), (("--tipo", "x.horas=number"), "--tipo"),
                            (("--tipo", "t.nada=number"), "--tipo"), (("--numeric", "horas", "--tipo", "t.horas=string"),
                                                                     "--tipo"),
                            (("--detector-max-filas", "0"), "--detector-max-filas")):
            error = self.query(*args, expected=2)["errores"][0]
            self.assertEqual(error["campo"], field, args)

    def test_read_only_non_finite_and_real_precision_still_hold_with_types(self):
        for sql in ("DELETE FROM t", "UPDATE t SET horas = 0", "SELECT 1; DROP TABLE t", "INSERT INTO t SELECT * FROM t"):
            self.assertIn("SQL", self.query("--tipo", "t.horas=number", sql=sql, expected=2)["error"])
        huge = self.write("huge.csv", "v\n" + "9" * 400 + "\n")
        overflow = self.query("--tipo", "t.v=number", sql="SELECT v FROM t", source=huge, expected=2)
        self.assertIn("desbordamiento", overflow["error"])
        long = self.write("long.csv", "v\n12345678901234567890\n")
        precise = self.query("--tipo", "t.v=number", sql="SELECT v FROM t", source=long, expected=1)
        self.assertEqual(precise["advertencias_por_codigo"], {"numeros_redondeados_por_precision_real": 1})
        self.assertEqual(precise["resultado"]["filas"], [{"v": "12345678901234567000"}])  # REAL: no es exacto

    def test_recipe_types_and_detector_options(self):
        def recipe(**params):
            return {"version": 1, "entradas": {"t": {"principal": True, "delimiter": ";", "decimal": ","},
                                               "f": {"ruta": "flota.csv", "delimiter": ";"}},
                    "pasos": [{"nombre": "sql", "op": "consultar", "tablas": {"t": "t", "f": "f"}, "sql": SQL, **params}]}

        def run(config, expected):
            path = self.write("receta.json", config)
            result = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), "ejecutar", str(self.ordenes), "--receta",
                                     str(path), "--output", str(self.folder / "rec"), "--json"],
                                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, expected, result.stdout)
            return json.loads(result.stdout)

        typed = run(recipe(tipos={"t": {"horas": "number"}}), 0)
        rows = (Path(typed["ruta_resultados"]) / "01-sql" / "resultado.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(rows, ["total;mayor", "6;010"])  # delimitador de salida: el de la entrada principal
        stopped = run(recipe(detector_max_filas=4), 2)  # advertencia no permitida: la política detiene
        self.assertEqual(stopped["errores"][0]["codigo"], "advertencias_no_admitidas")
        self.assertIn("detector_texto_numerico_omitido", stopped["errores"][0]["mensaje"])
        self.assertEqual(run(recipe(detector=False), 0)["estado"], "completada")
        bad = run(recipe(tipos={"x": {"horas": "number"}}), 2)["errores"][0]
        self.assertEqual((bad["codigo"], bad["campo"]), ("parametro_invalido", "tipos"))


if __name__ == "__main__":
    unittest.main()

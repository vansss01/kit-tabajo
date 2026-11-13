import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kitlib.cli import clean
from kitlib.runtime import configure, inside
from kitlib.tableio import Options, Table, csv_write, excel_write, number, read_table, real_text
from kitlib.operations import compare, inspect_table, transform, validate

configure()


class KitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="prueba con espacios-", dir=ROOT / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.opts = Options(delimiter=";", decimal=",")

    def csv(self, content, name="entrada á.csv", encoding="utf-8"):
        path = self.folder / name
        path.write_text(content, encoding=encoding)
        return path

    def read(self, content, opts=None):
        return read_table(self.csv(content), opts or self.opts)

    def cli(self, command, input_path, *extra, expected=0):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), command, str(input_path),
            "--output", str(self.folder / "salidas"), "--json", *map(str, extra)],
            text=True, capture_output=True, cwd=ROOT, encoding="utf-8")
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_empty_file_and_header_only(self):
        self.assertEqual(self.read("").issues[0]["codigo"], "archivo_vacio")
        t = self.read("id;valor\n")
        self.assertEqual(t.rows, [])
        self.assertEqual(t.warnings, ["sin_filas_de_datos"])

    def test_missing_required_column(self):
        t = self.read("id\n001\n")
        tables, issues, _ = validate(t, {"columns": {"fecha": {"required": True}}}, self.opts)
        self.assertEqual(tables["validos"].rows, [])
        self.assertEqual(len(tables["invalidos"].rows), 1)
        self.assertEqual(issues[0]["codigo"], "columna_obligatoria_ausente")

    def test_duplicate_and_empty_keys_block_comparison(self):
        t = self.read("id;v\n001;a\n001;b\n ;c\n")
        tables, issues, counts = compare(t, t, ["id"])
        self.assertFalse(tables)
        self.assertTrue(counts["comparacion_bloqueada"])
        self.assertEqual({i["codigo"] for i in issues}, {"clave_duplicada", "clave_vacia"})

    def test_composite_keys_and_detailed_changes(self):
        a = self.read("id;turno;v\n001;a;1\n001;b;2\n002;a;3\n")
        b = self.read("id;turno;v\n001;a;9\n001;b;2\n003;a;4\n")
        tables, issues, counts = compare(a, b, ["id", "turno"])
        self.assertFalse(issues)
        self.assertEqual([counts[k] for k in ("nuevos", "eliminados", "modificados", "sin_cambios")], [1, 1, 1, 1])
        self.assertEqual(tables["cambios"].rows[0]["antes"], "1")
        self.assertEqual(tables["cambios"].rows[0]["despues"], "9")

    def test_leading_zero_inspection_validation_roundtrip(self):
        t = self.read("id;v\n0007;2,50\n")
        self.assertEqual(inspect_table(t, self.opts, 1)["columnas"]["id"]["tipos_inferidos"], {"codigo_texto": 1})
        validate(t, {"columns": {"id": {"type": "integer"}}}, self.opts)
        self.assertEqual(t.rows[0]["id"], "0007")
        path = self.folder / "salida.csv"
        csv_write(path, t, ";")
        self.assertEqual(read_table(path, self.opts).rows, t.rows)

    def test_ambiguous_date_requires_explicit_format(self):
        t = self.read("fecha\n03/04/2026\n")
        rules = {"columns": {"fecha": {"type": "date"}}}
        self.assertTrue(validate(t, rules, self.opts)[1])
        opts = replace(self.opts, date_format="%d/%m/%Y")
        self.assertFalse(validate(t, rules, opts)[1])
        result, _, _ = transform(t, {"steps": [{"op": "convert", "column": "fecha", "type": "date"}]}, opts)
        self.assertEqual(result["validos"].rows[0]["fecha"], "2026-04-03")
        self.assertEqual(t.rows[0]["fecha"], "03/04/2026")

    def test_decimal_encoding_delimiter(self):
        p = self.csv("id;nombre;horas\n0001;Piñón;2,50\n", encoding="cp1252")
        t = read_table(p, replace(self.opts, encoding="cp1252"))
        rules = {"columns": {"horas": {"type": "number", "min": "2,4", "max": "2,6", "decimal": ","}}}
        self.assertFalse(validate(t, rules, self.opts)[1])
        self.assertEqual(t.rows[0]["nombre"], "Piñón")
        self.assertTrue(validate(t, {"columns": {"horas": {"type": "number"}}}, Options())[1])

    def test_sample_counts_are_not_estimates(self):
        p = self.csv("id\n1\n2\n3\n")
        t = read_table(p, limit=2)
        stats = inspect_table(t, Options(), 1)
        self.assertEqual(stats["alcance"], "muestra_inicial")
        self.assertIsNone(stats["filas_totales"])
        self.assertEqual(stats["filas_analizadas"], 2)
        self.assertEqual(len(stats["muestra"]), 1)
        self.assertTrue(read_table(p, limit=3).complete)

    def test_bad_headers_and_row_width(self):
        self.assertTrue(self.read("id;id\n1;2\n").issues)
        self.assertTrue(self.read("id;\n1;2\n").issues)
        t = self.read("id;v\n1;2;3\n2;x\n")
        self.assertEqual((t.scanned, len(t.rows), len(t.issues)), (2, 1, 1))
        self.assertEqual(t.row_numbers, [3])

    def test_unique_validation_marks_all_duplicates(self):
        t = self.read("id\n001\n001\n\n")
        tables, issues, _ = validate(t, {"columns": {"id": {"unique": True}}}, self.opts)
        self.assertEqual(len(tables["invalidos"].rows), 2)
        self.assertEqual(len([i for i in issues if i["codigo"] == "valor_no_unico"]), 2)

    def test_consolidation_rejects_incompatible_and_reorders(self):
        folder = self.folder / "lotes"
        folder.mkdir()
        (folder / "a.csv").write_text("id;v\n001;x\n", encoding="utf-8")
        (folder / "b.csv").write_text("v;id\ny;002\n", encoding="utf-8")
        (folder / "c.csv").write_text("id;extra\n003;z\n", encoding="utf-8")
        result = self.cli("consolidar", folder, "--delimiter", ";", expected=1)
        run = Path(result["ruta_resultados"])
        data = json.loads((run / "validos.json").read_text())
        self.assertEqual(len(data["rows"]), 2)
        self.assertEqual(data["rows"][1]["id"], "002")
        self.assertIn("__archivo_origen", data["columns"])
        details = json.loads((run / "report.json").read_text())["detalle"]
        self.assertEqual(len(details["rechazados"]), 1)

    def test_outputs_excluded_on_repeat(self):
        folder = self.folder / "lotes"
        folder.mkdir()
        (folder / "a.csv").write_text("id\n001\n", encoding="utf-8")
        output = folder / "resultado propio"
        first = self.cli("consolidar", folder, "--recursive", "--output", output)
        second = self.cli("consolidar", folder, "--recursive")
        self.assertEqual(first["filas_procesadas"], 1)
        self.assertEqual(second["filas_procesadas"], 1)

    def test_no_overwrite_and_original_hashes(self):
        p = self.csv("id\n0007\n")
        before = hashlib.sha256(p.read_bytes()).hexdigest()
        self.cli("exportar", p, "--run-name", "fijo")
        output = self.folder / "salidas" / "fijo" / "resultado.xlsx"
        saved = output.read_bytes()
        self.cli("exportar", p, "--run-name", "fijo", expected=2)
        self.assertEqual(saved, output.read_bytes())
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), before)
        with self.assertRaises(FileExistsError):
            csv_write(p, read_table(p))

    def test_path_sandbox(self):
        with self.assertRaises(ValueError):
            inside(ROOT.parent / "fuera.csv")
        link = self.folder / "enlace"
        try:
            link.symlink_to(ROOT.parent, target_is_directory=True)
        except OSError:
            self.skipTest("El sistema no permite crear enlaces simbólicos")
        with self.assertRaises(ValueError):
            inside(link / "fuera.csv")

    def test_transform_all_operations_explicit(self):
        t = self.read("id;horas;estado\n0007;2,5;abierta\n0007;2,5;abierta\n0042;4,0;cerrada\n")
        plan = {"steps": [{"op": "deduplicate", "keys": ["id"]},
            {"op": "filter", "column": "estado", "operator": "eq", "value": "abierta"},
            {"op": "convert", "column": "horas", "type": "number"},
            {"op": "sort", "columns": ["horas"], "type": "number", "decimal": "."},
            {"op": "select", "columns": ["id", "horas"]}]}
        tables, _, _ = transform(t, plan, self.opts)
        self.assertEqual(tables["validos"].rows, [{"id": "0007", "horas": "2.5"}])
        self.assertEqual(len(t.rows), 3)
        self.assertEqual(t.rows[0]["horas"], "2,5")

    def test_aggregation_exact_decimal(self):
        t = self.read("equipo;horas\n0007;0,1\n0007;0,2\n")
        plan = {"steps": [{"op": "group", "by": ["equipo"], "aggregates": [
            {"op": "sum", "column": "horas", "as": "total"},
            {"op": "mean", "column": "horas", "as": "media"},
            {"op": "count", "as": "cantidad"}]}]}
        rows = transform(t, plan, self.opts)[0]["validos"].rows
        self.assertEqual(rows, [{"equipo": "0007", "total": "0.3", "media": "0.15", "cantidad": "2"}])

    def test_arbitrary_code_and_unknown_rules_rejected(self):
        t = self.read("id\n001\n")
        with self.assertRaises(ValueError):
            transform(t, {"steps": [{"op": "eval", "code": "__import__('os')"}]}, self.opts)
        with self.assertRaises(ValueError):
            validate(t, {"columns": {"id": {"typo": True}}}, self.opts)
        with self.assertRaises(ValueError):
            transform(t, {"steps": [{"op": "filter", "column": "id", "operator": "eval", "value": "x"}]}, self.opts)

    def test_excel_sheets_styles_zeroes_and_formula_safety(self):
        from openpyxl import load_workbook
        p = self.folder / "libro con espacios.xlsx"
        t = Table(["id", "formula"], [{"id": "0007", "formula": "=1+1"}])
        excel_write(p, {"validos": t, "incidencias": Table(["codigo"], []), "resumen": Table(["n"], [{"n": "1"}])})
        with self.assertRaises(ValueError):
            read_table(p)
        loaded = read_table(p, Options(sheet="validos"))
        self.assertEqual(loaded.rows, t.rows)
        book = load_workbook(p)
        self.assertEqual(book.sheetnames, ["validos", "incidencias", "resumen"])
        self.assertEqual(book["validos"]["B2"].data_type, "s")
        self.assertTrue(book["validos"]["A1"].font.bold)
        self.assertEqual(book["validos"].freeze_panes, "A2")
        self.assertEqual(book["validos"].auto_filter.ref, "A1:B2")
        book.close()
        self.cli("inspeccionar", p, expected=1)

    def test_excel_formula_and_formatted_numeric_code_warnings(self):
        from openpyxl import Workbook
        p = self.folder / "formulas.xlsx"
        book = Workbook()
        ws = book.active
        ws.append(["id", "formula"])
        ws.append([7, "=1+1"])
        ws["A2"].number_format = "0000"
        book.save(p)
        book.close()
        t = read_table(p)
        self.assertIn("formulas_leidas_como_texto_no_evaluadas", t.warnings)
        self.assertIn("codigos_numericos_con_formato_de_ceros_no_recuperado", t.warnings)
        self.assertEqual(t.rows[0]["id"], "7")
        self.cli("inspeccionar", p, expected=1)

    def test_csv_formula_neutralization_is_explicit(self):
        t = Table(["v"], [{"v": "=1+1"}])
        raw, safe = self.folder / "raw.csv", self.folder / "safe.csv"
        self.assertEqual(csv_write(raw, t), 0)
        self.assertEqual(csv_write(safe, t, safe=True), 1)
        self.assertEqual(read_table(raw).rows[0]["v"], "=1+1")
        self.assertEqual(read_table(safe).rows[0]["v"], "'=1+1")

    def test_export_validation_separates_results(self):
        p = self.csv("id;horas\n0001;2,5\n0002;-1\n")
        rules = self.folder / "reglas.json"
        rules.write_text(json.dumps({"columns": {"horas": {"type": "number", "decimal": ",", "min": "0"}}}))
        summary = self.cli("exportar", p, "--delimiter", ";", "--rules", rules, expected=1)
        run = Path(summary["ruta_resultados"])
        valid = json.loads((run / "validos.json").read_text())["rows"]
        invalid = json.loads((run / "invalidos.json").read_text())["rows"]
        self.assertEqual((len(valid), len(invalid), summary["incidencias"]), (1, 1, 1))
        self.assertTrue((run / "resultado.xlsx").exists())

    def test_originals_unchanged_across_all_commands(self):
        p = self.csv("id;v\n001;2\n")
        original = p.read_bytes()
        rules = self.folder / "rules.json"
        rules.write_text('{"columns":{"id":{"required":true}}}')
        plan = self.folder / "plan.json"
        plan.write_text('{"steps":[{"op":"select","columns":["id"]}]}')
        self.cli("inspeccionar", p, "--delimiter", ";")
        self.cli("validar", p, "--delimiter", ";", "--rules", rules)
        self.cli("comparar", p, p, "--delimiter", ";", "--key", "id")
        self.cli("transformar", p, "--delimiter", ";", "--plan", plan)
        self.cli("exportar", p, "--delimiter", ";")
        self.assertEqual(original, p.read_bytes())

    def test_cli_codes_and_invalid_arguments(self):
        p = self.csv("id\n001\n")
        self.assertEqual(self.cli("inspeccionar", p)["codigo_salida"], 0)
        sample = self.cli("inspeccionar", p, "--sample", "21", expected=2)["errores"][0]
        self.assertEqual((sample["codigo"], sample["campo"]), ("argumento_invalido", "--sample"))
        missing = self.cli("exportar", self.folder / "inexistente.csv", expected=2)
        self.assertEqual(missing["errores"][0]["codigo"], "archivo_no_encontrado")
        empty = self.cli("inspeccionar", self.csv("", "vacio.csv"), expected=1)
        self.assertEqual((empty["filas_procesadas"], empty["incidencias_por_codigo"]), (0, {"archivo_vacio": 1}))
        reserved = self.cli("inspeccionar", p, "--run-name", "NUL", expected=2)["errores"][0]
        self.assertEqual((reserved["codigo"], reserved["campo"]), ("argumento_invalido", "--run-name"))

    def test_table_json_is_one_row_per_line_and_excel_keeps_error_like_text(self):
        table = Table(["id", "v"], [{"id": "001", "v": "#N/A"}, {"id": "002", "v": None}])
        from kitlib.tableio import table_json
        table_json(self.folder / "t.json", table)
        text = (self.folder / "t.json").read_text(encoding="utf-8")
        self.assertEqual(len(text.splitlines()), 5)
        self.assertEqual(json.loads(text), {"columns": table.columns, "rows": table.rows})
        self.assertEqual(read_table(self.folder / "t.json").rows, table.rows)
        excel_write(self.folder / "t.xlsx", {"datos": table})
        back = read_table(self.folder / "t.xlsx")
        self.assertEqual(back.rows, table.rows)
        self.assertEqual(back.warnings, [])

    def test_help_all_commands(self):
        """La ayuda de cada comando sale por stdout y nombra sus opciones (hallazgo 5 de la auditoría 1.5.0: antes
        solo se miraba el código de salida y la prueba pasaba con la ayuda vacía). Textos esperados a mano."""
        common = ["--delimiter", "--encoding", "--decimal", "--date-format", "--sheet", "--output", "--run-name",
                  "--json", "--verbose", "--ocultar-valores"]
        expected = {
            (): ["inspeccionar", "comparar", "consolidar", "validar", "transformar", "exportar", "consultar", "ejecutar",
                 "bitacora", "limpiar", "catalogo", "comprobar", "resultados", "Sin IA ni servicios externos"],
            ("inspeccionar",): common + ["--sample", "--limit", "Filas de muestra"],
            ("comparar",): common + ["after", "--key", "--after-sheet", "Una o más columnas clave"],
            ("consolidar",): common + ["--glob", "--recursive", "--exclude"],
            ("validar",): common + ["--rules", "Reglas JSON de validación"],
            ("transformar",): common + ["--plan"],
            ("exportar",): common + ["--rules", "--format", "--safe-csv"],
            ("consultar",): common + ["--sql", "--tabla", "--tipo", "--numeric", "--show", "--detector-max-filas"],
            ("ejecutar",): ["--receta", "--entrada", "--vista-previa", "--output", "--json", "--ocultar-valores"],
            ("limpiar",): ["--keep", "--apply", "--json"],
            ("bitacora",): ["--horas", "--etiqueta", "--ver", "--informe", "--desde", "--hasta"],
            ("catalogo",): ["usage:"],
            ("comprobar",): ["archivo", "--tipo", "--principal", "--json"],
            ("resultados",): ["--paso", "--incidencias", "--n", "--json"],
        }
        for command, texts in expected.items():
            result = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), *command, "--help"], capture_output=True,
                                    text=True, encoding="utf-8")
            self.assertEqual((result.returncode, result.stderr), (0, ""), command)
            self.assertTrue(result.stdout.startswith("usage: "), command)
            for text in texts:
                self.assertIn(text, result.stdout, command)


    def test_global_decimal_and_date_format_apply_to_bounds(self):
        t = self.read("v;fecha\n2,5;03/04/2026\n")
        rules = {"columns": {"v": {"type": "number", "min": "2,4", "max": "2,6"},
                              "fecha": {"type": "date", "min": "01/04/2026", "max": "30/04/2026"}}}
        self.assertFalse(validate(t, rules, replace(self.opts, date_format="%d/%m/%Y"))[1])

    def test_invalid_or_empty_bounds_are_configuration_errors(self):
        t = self.read("v\n2\n")
        for spec in ({"type": "number", "min": "3", "max": "1"}, {"type": "number", "min": None}):
            with self.assertRaises(ValueError):
                validate(t, {"columns": {"v": spec}}, self.opts)

    def test_invalid_header_never_claims_exact_zero_rows(self):
        t = self.read("id;id\n1;2\n3;4\n")
        stats = inspect_table(t, self.opts, 0)
        self.assertIsNone(stats["filas_totales"])
        self.assertEqual(stats["alcance"], "estructura_no_analizable")

    def test_sum_preserves_more_than_28_digits(self):
        t = self.read("v\n999999999999999999999999999999\n1\n")
        plan = {"steps": [{"op": "group", "by": [], "aggregates": [{"op": "sum", "column": "v", "as": "total"}]}]}
        rows = transform(t, plan, self.opts)[0]["validos"].rows
        self.assertEqual(rows, [{"total": "1000000000000000000000000000000"}])

    def test_empty_excel_and_long_cell_rejection(self):
        from openpyxl import Workbook
        p = self.folder / "vacio.xlsx"
        book = Workbook()
        book.save(p)
        book.close()
        self.assertEqual(read_table(p).issues[0]["codigo"], "archivo_vacio")
        with self.assertRaises(ValueError):
            excel_write(self.folder / "largo.xlsx", {"datos": Table(["v"], [{"v": "x" * 32768}])})
        self.assertFalse((self.folder / "largo.xlsx").exists())

    def test_failed_transform_marks_incomplete_run_without_table(self):
        p = self.csv("v\ntexto\n")
        plan = self.folder / "plan.json"
        plan.write_text('{"steps":[{"op":"convert","column":"v","type":"number"}]}')
        summary = self.cli("transformar", p, "--plan", plan, expected=2)
        run = Path(summary["ruta_resultados"])
        self.assertTrue((run / "FAILED.json").exists())
        self.assertFalse((run / "validos.json").exists())
        self.assertNotIn("texto", summary["error"])

    def test_json_schema_and_null_roundtrip(self):
        from kitlib.tableio import table_json
        p = self.folder / "tabla.json"
        t = Table(["id", "v"], [{"id": "0007", "v": None}, {"id": "0008", "v": ""}])
        table_json(p, t)
        self.assertEqual(read_table(p).rows, t.rows)
        bad = self.folder / "mala.json"
        bad.write_text('{"columns":["id"],"rows":[{"otra":"1"}]}')
        with self.assertRaises(ValueError):
            read_table(bad)

    def test_numeric_filter_and_sort_and_min_max(self):
        t = self.read("id;v\n1;10\n2;2\n3;1\n")
        plan = {"steps": [{"op": "filter", "column": "v", "operator": "ge", "type": "number", "value": "2"},
                           {"op": "sort", "columns": ["v"], "type": "number"}]}
        result = transform(t, plan, self.opts)[0]["validos"]
        self.assertEqual([r["v"] for r in result.rows], ["2", "10"])
        grouped = {"steps": [{"op": "group", "by": [], "aggregates": [
            {"op": "min", "column": "v", "as": "menor"}, {"op": "max", "column": "v", "as": "mayor"}]}]}
        self.assertEqual(transform(result, grouped, self.opts)[0]["validos"].rows, [{"menor": "2", "mayor": "10"}])

    def test_wrong_delimiter_is_warned_not_silent(self):
        p = self.csv("id;valor\n001;a\n")
        summary = self.cli("inspeccionar", p, expected=1)
        self.assertEqual(summary["advertencias_por_codigo"], {"posible_delimitador_incorrecto": 1})
        self.assertEqual(summary["sugerencia"], "--delimiter ';'")
        bad = self.cli("inspeccionar", self.csv("id;v\n1;año\n", "latin.csv", "cp1252"), "--delimiter", ";", expected=2)
        self.assertIn("--encoding cp1252", bad["error"])
        self.assertIn("No existe", self.cli("inspeccionar", self.folder / "falta.csv", expected=2)["error"])
        before = len(list((ROOT / "logs").iterdir()))
        self.cli("inspeccionar", p, "--delimiter", ";")
        self.assertEqual(len(list((ROOT / "logs").iterdir())), before)
        self.assertEqual(self.cli("inspeccionar", p, "--delimiter", ";")["tablas"][0]["columnas"], ["id", "valor"])
        self.assertEqual(self.read("a,b\n1\n", Options(delimiter=",")).warnings, [])

    def test_terminal_summary_has_codes_and_counts_without_cell_values(self):
        p = self.csv("id;v\nSECRETO;1\nSECRETO;x\n")
        rules = self.folder / "reglas.json"
        rules.write_text(json.dumps({"columns": {"id": {"unique": True}, "v": {"type": "integer"}}}), encoding="utf-8")
        result = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), "validar", str(p), "--delimiter", ";",
            "--rules", str(rules), "--output", str(self.folder / "salidas"), "--json"],
            text=True, capture_output=True, cwd=ROOT, encoding="utf-8")
        summary = json.loads(result.stdout)
        self.assertEqual(summary["incidencias_por_codigo"], {"valor_no_unico": 2, "tipo_o_fecha_invalido": 1})
        self.assertEqual(summary["conteos"], {"validas": 0, "invalidas": 2, "filas_no_tabulares": 0})
        self.assertNotIn("SECRETO", result.stdout)

    def test_clean_is_dry_by_default_and_only_removes_marked_runs(self):
        results, logs = self.folder / "results", self.folder / "logs"
        results.mkdir()
        logs.mkdir()
        for i in range(4):
            run = results / f"run{i}"
            run.mkdir()
            (run / ".kit-output").touch()
            (run / "report.json").write_text("{}", encoding="utf-8")
            (logs / f"run{i}-0123abcd.json").write_text("{}", encoding="utf-8")
        (results / "ajena").mkdir()
        (results / "ajena" / "datos.csv").write_text("a\n", encoding="utf-8")
        (logs / "storage.json").write_text("{}", encoding="utf-8")
        dry = clean(1, False, results, logs)
        self.assertEqual((dry["ejecuciones_antiguas"], dry["registros_antiguos"], dry["aplicado"]), (3, 3, False))
        self.assertEqual(len(list(results.iterdir())), 5)
        clean(1, True, results, logs)
        self.assertEqual(len([p for p in results.iterdir() if (p / ".kit-output").exists()]), 1)
        self.assertTrue((results / "ajena" / "datos.csv").exists())
        self.assertEqual(sorted(p.name for p in logs.iterdir() if p.name != "storage.json").__len__(), 1)
        self.assertTrue((logs / "storage.json").exists())
        with self.assertRaises(ValueError):
            clean(1, True, ROOT.parent, logs)

    def test_sql_query_join_numeric_and_read_only(self):
        orders = self.csv("orden;equipo;horas\nA;0007;2,5\nB;0007;x\nC;0099;1,0\n", "ordenes.csv")
        fleet = self.csv("equipo;area\n0007;Mina\n", "flota.csv")
        common = ("--delimiter", ";", "--decimal", ",")
        result = self.cli("consultar", orders, *common, "--numeric", "horas", "--tabla", f"flota={fleet}", "--sql",
                          "SELECT t.equipo, f.area, SUM(t.horas) AS horas FROM t LEFT JOIN flota f ON f.equipo = t.equipo "
                          "GROUP BY t.equipo ORDER BY t.equipo", expected=1)
        self.assertEqual(result["resultado"]["filas"], [{"equipo": "0007", "area": "Mina", "horas": "2.5"},
                                                        {"equipo": "0099", "area": None, "horas": "1"}])
        self.assertEqual(result["advertencias_por_codigo"], {"valores_no_numericos_cargados_como_null": 1})
        hidden = self.cli("consultar", orders, *common, "--show", "0", "--sql", "SELECT orden FROM t")
        self.assertNotIn("resultado", hidden)
        target = self.folder / "fuga.db"
        for sql in ("DROP TABLE t", "DELETE FROM t", f"ATTACH '{target.as_posix()}' AS x", "SELECT 1; SELECT 2",
                    "PRAGMA table_info(t)", "CREATE TABLE z AS SELECT * FROM t", "no es sql"):
            self.assertIn("SQL", self.cli("consultar", orders, *common, "--sql", sql, expected=2)["error"])
        self.assertFalse(target.exists())

    def test_allowed_values_rule(self):
        t = self.read("id;estado\n1;abierta\n2;Cerrada\n3;\n")
        tables, issues, _ = validate(t, {"columns": {"estado": {"allowed": ["abierta", "cerrada"]}}}, self.opts)
        self.assertEqual([(i["codigo"], i["fila"]) for i in issues], [("valor_no_permitido", 3)])
        with self.assertRaises(ValueError):
            validate(t, {"columns": {"estado": {"allowed": []}}}, self.opts)

    def test_logbook_appends_and_builds_weekly_report(self):
        book = self.folder / "bitacora.csv"

        def run(*extra, expected=0):
            result = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), "bitacora", *extra, "--archivo", str(book),
                                     "--json"], text=True, capture_output=True, cwd=ROOT, encoding="utf-8")
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            return json.loads(result.stdout)

        run("Inducción; con punto y coma", "--horas", "4", "--fecha", "2026-12-01", "--etiqueta", "Inducción")
        first = book.read_bytes()
        self.assertEqual(run("Planilla de órdenes", "--horas", "2,5", "--fecha", "2026-12-09")["anotaciones"], 2)
        self.assertTrue(book.read_bytes().startswith(first))
        self.assertEqual(run("--ver")["anotaciones"][0]["texto"], "Inducción; con punto y coma")
        summary = run("--informe")
        self.assertEqual((summary["semanas"], summary["dias"], summary["horas"]), (2, 2, "6.5"))
        text = (Path(summary["ruta_resultados"]) / "informe_practica.md").read_text(encoding="utf-8")
        self.assertIn("### Semana 2 (2026-12-07 a 2026-12-13)", text)
        self.assertIn("| inducción | 1 | 4 |", text)
        run("x", "--horas", "30", expected=2)
        run("x", "--fecha", "01/12/2026", expected=2)
        run(expected=2)
        self.assertEqual(len(book.read_text(encoding="utf-8").splitlines()), 3)

    def test_mining_practice_data_matches_its_declared_errors(self):
        target = self.folder / "minera"
        subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "datos_mineros.py"), "--output", str(target)],
                       check=True, capture_output=True, cwd=ROOT)
        declared = json.loads((target / "respuestas.json").read_text(encoding="utf-8"))["errores_inyectados"]
        codes = self.cli("validar", target / "ordenes.csv", "--delimiter", ";", "--rules", target / "reglas_ordenes.json",
                         expected=1)["incidencias_por_codigo"]
        self.assertEqual(codes["valor_no_unico"], 2 * declared["orden_duplicada"])
        self.assertEqual(codes["campo_vacio"], declared["equipo_vacio"] + declared["horas_vacias"])
        self.assertEqual(codes["tipo_o_fecha_invalido"], declared["fecha_formato_dia_mes_año"])
        self.assertEqual(codes["valor_no_permitido"], declared["estado_mal_escrito"])
        self.assertEqual((codes["fuera_de_rango_min"], codes["fuera_de_rango_max"]),
                         (declared["horas_negativas"], declared["horas_sobre_72"]))
        counts = self.cli("comparar", target / "flota_anterior.csv", target / "flota.csv", "--delimiter", ";",
                          "--key", "equipo")["conteos"]
        self.assertEqual((counts["nuevos"], counts["eliminados"], counts["modificados"]), (2, 1, 6))
        self.cli("inspeccionar", target / "flota_excel_windows.csv", "--delimiter", ";", expected=2)
        self.cli("inspeccionar", target / "flota_excel_windows.csv", "--delimiter", ";", "--encoding", "cp1252")

    # --- consultar: representación numérica, rango y omisión de --numeric (1.4.1) ---

    def saved(self, summary):
        """Filas de validos.json, tras comprobar que validos.csv guarda lo mismo (null = campo vacío)."""
        run = Path(summary["ruta_resultados"])
        data = json.loads((run / "validos.json").read_text(encoding="utf-8"))
        with (run / "validos.csv").open(encoding="utf-8", newline="") as stream:
            lines = list(csv.reader(stream, delimiter=";"))
        self.assertEqual(lines, [data["columns"]] + [[r[c] or "" for c in data["columns"]] for r in data["rows"]])
        return data["rows"]

    def assert_failed_without_tables(self, summary):
        run = Path(summary["ruta_resultados"])
        self.assertTrue((run / "FAILED.json").exists())
        self.assertEqual([p.name for p in run.iterdir() if p.name.startswith("validos")], [])

    def test_float_text_is_plain_decimal_and_reads_back_to_the_same_float(self):
        self.assertEqual(real_text(1234567890123.0), "1234567890123")
        self.assertEqual(real_text(1e-07), "0.0000001")
        self.assertEqual(real_text(0.1), "0.1")
        self.assertEqual(real_text(-2.5), "-2.5")
        self.assertEqual(real_text(-0.0), "0")
        self.assertEqual(real_text(1e22), "1" + "0" * 22)
        self.assertEqual(real_text(1 / 3), "0.3333333333333333")
        for value in (5e-324, 1.7976931348623157e308, -1.2345678901234567e-300, 0.1 + 0.2, 123456789.12345679):
            text = real_text(value)
            self.assertEqual(float(number(text)), value)  # admitido por el kit y sin pérdida añadida
            self.assertNotIn("e", text.lower())

    def test_sql_numbers_survive_query_validation_and_exact_transform(self):
        source = self.csv("id;v\n1;1234567890123\n2;0,0000001\n3;-2,5\n4;0\n5;\n", "numeros.csv")
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        result = self.cli("consultar", source, "--delimiter", ";", "--decimal", ",", "--numeric", "v",
                          "--show", "0", "--sql", "SELECT id, v FROM t ORDER BY id")
        self.assertEqual(result["estado"], "ok")
        self.assertEqual(self.saved(result), [
            {"id": "1", "v": "1234567890123"}, {"id": "2", "v": "0.0000001"}, {"id": "3", "v": "-2.5"},
            {"id": "4", "v": "0"}, {"id": "5", "v": None}])
        run = Path(result["ruta_resultados"])
        rules = self.folder / "reglas numero.json"
        rules.write_text('{"columns":{"v":{"type":"number"}}}', encoding="utf-8")
        plan = self.folder / "plan suma.json"
        plan.write_text('{"steps":[{"op":"group","by":[],"aggregates":[{"op":"sum","column":"v","as":"total"},'
                        '{"op":"count","column":"v","as":"n"}]}]}', encoding="utf-8")
        for name in ("validos.csv", "validos.json"):  # la salida usa punto decimal: --decimal . en adelante
            checked = self.cli("validar", run / name, "--delimiter", ";", "--rules", rules)
            self.assertEqual(checked["conteos"]["validas"], 5)
            total = self.cli("transformar", run / name, "--delimiter", ";", "--plan", plan)
            # 1234567890123 + 0.0000001 − 2.5 + 0, calculado a mano.
            self.assertEqual(self.saved(total), [{"total": "1234567890120.5000001", "n": "4"}])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_sql_rejects_input_overflow_and_underflow_without_publishing(self):
        common = ("--numeric", "v", "--show", "0", "--sql", "SELECT v FROM t")
        cases = {"desbordamiento": "9" * 400, "subdesbordamiento": "0." + "0" * 400 + "7"}
        for kind, cell in cases.items():
            source = self.csv("v\n1.5\n" + cell + "\n", kind + ".csv")
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            failed = self.cli("consultar", source, *common, expected=2)
            self.assertIn("tabla t, columna v: 1 por " + kind, failed["error"])
            self.assertNotIn(cell[:6], failed["error"])  # sin contenido de celdas
            self.assert_failed_without_tables(failed)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        # Política previa intacta: vacío = NULL sin aviso; texto no numérico = NULL con advertencia.
        blank = self.cli("consultar", self.csv("v\n1.5\n\"\"\n", "vacio.csv"), *common)
        self.assertEqual(self.saved(blank), [{"v": "1.5"}, {"v": None}])
        text = self.cli("consultar", self.csv("v\n1.5\nN/D\n", "texto.csv"), *common, expected=1)
        self.assertEqual(text["advertencias_por_codigo"], {"valores_no_numericos_cargados_como_null": 1})
        self.assertEqual(self.saved(text), [{"v": "1.5"}, {"v": None}])

    def test_sql_rejects_overflow_in_computed_results(self):
        source = self.csv("v\n1" + "0" * 200 + "\n", "grande.csv")
        fine = self.cli("consultar", source, "--numeric", "v", "--show", "0", "--sql", "SELECT v FROM t")
        self.assertEqual(self.saved(fine), [{"v": "1" + "0" * 200}])
        failed = self.cli("consultar", source, "--numeric", "v", "--sql", "SELECT 1 AS uno, v * v AS cuadrado FROM t",
                          expected=2)
        self.assertIn("desbordamiento", failed["error"])
        self.assertIn("cuadrado", failed["error"])
        self.assertNotIn("resultado", failed)
        self.assert_failed_without_tables(failed)
        # Sin --numeric SQLite convierte el texto por su cuenta: el infinito tampoco se publica.
        implicit = self.cli("consultar", self.csv("v\n" + "9" * 400 + "\n", "nueves.csv"),
                            "--sql", "SELECT SUM(v) AS s FROM t", expected=2)
        self.assert_failed_without_tables(implicit)

    def test_sql_warns_when_long_numbers_do_not_fit_real_precision(self):
        source = self.csv("v\n12345678901234567890\n0.1\n", "largo.csv")
        result = self.cli("consultar", source, "--numeric", "v", "--show", "0", "--sql", "SELECT v FROM t", expected=1)
        self.assertEqual(result["advertencias_por_codigo"], {"numeros_redondeados_por_precision_real": 1})
        self.assertEqual(result["conteos"]["valores_redondeados"], 1)
        self.assertEqual(self.saved(result), [{"v": "12345678901234567000"}, {"v": "0.1"}])

    def test_sql_decimal_comma_with_and_without_numeric(self):
        source = self.csv("v\n2,5\n3,5\n", "coma.csv")
        common = ("--delimiter", ";", "--decimal", ",", "--show", "0")
        total = "SELECT SUM(v) AS total FROM t"
        declared = self.cli("consultar", source, *common, "--numeric", "v", "--sql", total)
        self.assertEqual(self.saved(declared), [{"total": "6"}])  # 2,5 + 3,5
        # Salida compatible con 1.4.1: la traza de recetas no añade claves al uso suelto.
        self.assertEqual(declared["conteos"], {"filas_salida": 1, "valores_no_numericos": 0, "valores_redondeados": 0,
                                               "columnas_sin_numeric": 0})
        detail = json.loads((Path(declared["ruta_resultados"]) / "report.json").read_text(encoding="utf-8"))["detalle"]
        self.assertEqual(set(detail), {"filas_salida", "valores_no_numericos", "valores_redondeados",
                                       "columnas_sin_numeric"})
        omitted = self.cli("consultar", source, *common, "--sql", total, expected=1)
        self.assertEqual(omitted["advertencias_por_codigo"], {"resultado_depende_de_texto_sin_numeric": 1})
        self.assertIn("--numeric v", omitted["sugerencia"])
        report = json.loads((Path(omitted["ruta_resultados"]) / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["advertencias_detalle"][0]["columnas"], ["v"])
        self.assertEqual(report["detalle"]["columnas_sin_numeric"], ["v"])
        # Otros usos numéricos del mismo texto: operador, comparación y orden.
        ordered = self.csv("v\n10,5\n9,5\n", "orden.csv")
        for sql in ("SELECT v * 2 AS doble FROM t", "SELECT COUNT(*) AS n FROM t WHERE v > 9.9",
                    "SELECT v FROM t ORDER BY v"):
            warned = self.cli("consultar", ordered, *common, "--sql", sql, expected=1)
            self.assertEqual(warned["advertencias_por_codigo"], {"resultado_depende_de_texto_sin_numeric": 1}, sql)
        # Mostrar la columna tal cual no es un cálculo: sin aviso y sin cambiar el texto.
        shown = self.cli("consultar", source, *common, "--sql", "SELECT v FROM t")
        self.assertEqual(self.saved(shown), [{"v": "2,5"}, {"v": "3,5"}])

    def test_sql_usual_text_queries_stay_clean_and_keep_codes(self):
        orders = self.csv("orden;equipo;estado;horas\n1001;0007;abierta;2,5\n1002;0007;cerrada;10,0\n"
                          "1003;0099;abierta;1,5\n", "ordenes.csv")
        fleet = self.csv("equipo;area\n0007;Mina\n0099;Planta\n", "flota.csv")
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (orders, fleet)}
        common = ("--delimiter", ";", "--decimal", ",", "--show", "0", "--tabla", f"flota={fleet}")
        expected = {
            "SELECT estado, COUNT(*) AS n FROM t GROUP BY estado ORDER BY estado":
                [{"estado": "abierta", "n": "2"}, {"estado": "cerrada", "n": "1"}],
            "SELECT equipo FROM t WHERE equipo = '0007' ORDER BY orden": [{"equipo": "0007"}, {"equipo": "0007"}],
            "SELECT t.orden, f.area FROM t JOIN flota f ON f.equipo = t.equipo WHERE t.estado = 'abierta' ORDER BY t.orden":
                [{"orden": "1001", "area": "Mina"}, {"orden": "1003", "area": "Planta"}],
            "SELECT equipo, COUNT(DISTINCT orden) AS n FROM t GROUP BY equipo ORDER BY equipo":
                [{"equipo": "0007", "n": "2"}, {"equipo": "0099", "n": "1"}],
            "SELECT orden, equipo, horas FROM t WHERE estado = 'cerrada'":
                [{"orden": "1002", "equipo": "0007", "horas": "10,0"}],
        }
        for sql, rows in expected.items():
            clean_run = self.cli("consultar", orders, *common, "--sql", sql)  # código 0
            self.assertEqual(clean_run["advertencias"], 0, sql)
            self.assertEqual(self.saved(clean_run), rows, sql)
        by_team = "SELECT equipo, SUM(horas) AS horas FROM t GROUP BY equipo ORDER BY equipo"
        summed = self.cli("consultar", orders, *common, "--numeric", "horas", "--sql", by_team)
        self.assertEqual(self.saved(summed), [{"equipo": "0007", "horas": "12.5"}, {"equipo": "0099", "horas": "1.5"}])
        self.cli("consultar", orders, *common, "--sql", by_team, expected=1)
        # La repetición interna de la protección tampoco permite escribir ni varias sentencias.
        for sql in ("DELETE FROM t WHERE horas > 1", "UPDATE t SET horas = 0", "SELECT SUM(horas) FROM t; DROP TABLE t",
                    "CREATE TABLE z AS SELECT horas FROM t", "INSERT INTO t SELECT * FROM t"):
            self.assertIn("SQL", self.cli("consultar", orders, *common, "--sql", sql, expected=2)["error"])
        for path, digest in before.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()

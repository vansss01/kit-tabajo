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
from kitlib.tableio import Options, Table, csv_write, excel_write, read_table
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
            text=True, capture_output=True, cwd=ROOT)
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
        self.cli("inspeccionar", p, "--sample", "21", expected=2)
        self.cli("exportar", self.folder / "inexistente.csv", expected=2)
        self.cli("inspeccionar", self.csv("", "vacio.csv"), expected=1)

    def test_help_all_commands(self):
        for command in ([], ["inspeccionar"], ["comparar"], ["consolidar"], ["validar"], ["transformar"], ["exportar"], ["limpiar"]):
            result = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), *command, "--help"], capture_output=True)
            self.assertEqual(result.returncode, 0)


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
        self.assertEqual(self.cli("inspeccionar", p, "--delimiter", ";")["tablas"][0]["columnas"], ["id", "valor"])
        self.assertEqual(self.read("a,b\n1\n", Options(delimiter=",")).warnings, [])

    def test_terminal_summary_has_codes_and_counts_without_cell_values(self):
        p = self.csv("id;v\nSECRETO;1\nSECRETO;x\n")
        rules = self.folder / "reglas.json"
        rules.write_text(json.dumps({"columns": {"id": {"unique": True}, "v": {"type": "integer"}}}), encoding="utf-8")
        result = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), "validar", str(p), "--delimiter", ";",
            "--rules", str(rules), "--output", str(self.folder / "salidas"), "--json"],
            text=True, capture_output=True, cwd=ROOT)
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


if __name__ == "__main__":
    unittest.main()

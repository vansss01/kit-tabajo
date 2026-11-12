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


class Plain(Base):
    """Añade la ejecución de comandos sueltos (transformar, validar) con ; como delimitador."""

    def cli_plain(self, command, source, *extra, expected=0):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), command, str(source), "--delimiter", ";",
                                 "--output", str(self.out), "--json", *map(str, extra)],
                                text=True, capture_output=True, cwd=ROOT, encoding="utf-8")
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)


class RenombrarTests(Plain):
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


class NormalizarTests(Base):
    # fila 2: " OT1 ", "0007", "Abierta", "muy   largo" | fila 3: "OT1", "0012", " abierta ", ""
    # fila 4: "OT2", "  0042 ", "CERRADA", "é  á"
    DATA = "orden;equipo;estado;obs\n OT1 ;0007;Abierta;muy   largo\nOT1;0012; abierta ;\nOT2;  0042 ;CERRADA;é  á\n"
    PLAN = [{"op": "normalize", "columns": ["orden", "equipo", "obs"]},
            {"op": "normalize", "columns": ["estado"], "case": "lower"},
            {"op": "normalize", "columns": ["obs"], "case": "upper"}]

    def test_normalize_only_listed_columns_keeps_codes_and_accents_and_logs_every_change(self):
        source = self.write("espacios.csv", self.DATA)
        recipe = plan_recipe(*self.PLAN)
        summary = self.run_cli(recipe, source)
        run = Path(summary["ruta_resultados"]) / "01-paso"
        self.assertEqual(self.rows(run / "resultado.csv"), [
            ["orden", "equipo", "estado", "obs"], ["OT1", "0007", "abierta", "MUY LARGO"],
            ["OT1", "0012", "abierta", ""], ["OT2", "0042", "cerrada", "É Á"]])
        changes = [[r[2], r[3], r[4], r[5], r[6], r[7]] for r in self.rows(run / "cambios_celdas.csv")[1:]]
        self.assertEqual(changes, [  # por paso del plan y, dentro de él, columna por columna
            ["2", "orden", " OT1 ", "OT1", "normalize", "1"], ["4", "equipo", "  0042 ", "0042", "normalize", "1"],
            ["2", "obs", "muy   largo", "muy largo", "normalize", "1"], ["4", "obs", "é  á", "é á", "normalize", "1"],
            ["2", "estado", "Abierta", "abierta", "normalize lower", "2"],
            ["3", "estado", " abierta ", "abierta", "normalize lower", "2"],
            ["4", "estado", "CERRADA", "cerrada", "normalize lower", "2"],
            ["2", "obs", "muy largo", "MUY LARGO", "normalize upper", "3"],
            ["4", "obs", "é á", "É Á", "normalize upper", "3"]])
        report = json.loads((run / "report.json").read_text(encoding="utf-8"))["detalle"]["pasos"]
        self.assertEqual([p.get("valores_unificados") for p in report], [{"orden": 1}, {"estado": 1}, None])
        # Sin case no se cambia mayúsculas/minúsculas: "Abierta" sigue igual si solo se recorta.
        only_trim = self.run_cli(plan_recipe({"op": "normalize", "columns": ["estado"]}), source)
        self.assertEqual([r[2] for r in self.rows(Path(only_trim["ruta_resultados"]) / "01-paso" / "resultado.csv")[1:]],
                         ["Abierta", "abierta", "CERRADA"])

    def test_normalization_that_merges_keys_is_detected_downstream(self):
        source = self.write("espacios.csv", self.DATA)
        recipe = plan_recipe(self.PLAN[0])
        recipe["pasos"].append({"nombre": "claves", "op": "validar", "entrada": "paso.resultado",
                                "reglas": {"columns": {"orden": {"unique": True}}}, "politica": {"incidencias": "separar"}})
        summary = self.run_cli(recipe, source, expected=1)
        run = Path(summary["ruta_resultados"])
        # " OT1 " (fila 2) y "OT1" (fila 3) eran distintas; tras normalizar chocan y se separan.
        self.assertEqual([(r[3], r[4]) for r in self.rows(run / "02-claves" / "rechazadas_procedencia.csv")[1:]],
                         [("2", "valor_no_unico"), ("3", "valor_no_unico")])
        self.assertEqual([r[0] for r in self.rows(run / "02-claves" / "aceptadas.csv")[1:]], ["OT2"])

    def test_normalize_invalid_options(self):
        source = self.write("espacios.csv", self.DATA)
        for step, text in (({"op": "normalize", "columns": ["estado"], "case": "title"}, "case admite"),
                           ({"op": "normalize", "columns": []}, "lista no vacía")):
            error = self.run_cli(plan_recipe(step), source, expected=2)["errores"][0]
            self.assertEqual((error["codigo"], error["paso"], error["campo"]), ("configuracion_invalida", "paso", "plan"))
            self.assertIn(text, error["mensaje"])
        missing = self.run_cli(plan_recipe({"op": "normalize", "columns": ["Estado"]}), source, expected=2)
        self.assertEqual(missing["errores"][0]["codigo"], "columnas_incompatibles")


class ReemplazarTests(Plain):
    # filas 2..8 de estado: Abierta, abierta, ABIERTA, Cerrada, en proceso, (vacía), "abierta " (con espacio)
    DATA = ("orden;equipo;estado\nOT1;0007;Abierta\nOT2;0007;abierta\nOT3;0012;ABIERTA\nOT4;0042;Cerrada\n"
            "OT5;0042;en proceso\nOT6;0099;\nOT7;0099;abierta \n")
    MAP = {"Abierta": "abierta", "ABIERTA": "abierta", "Cerrada": "cerrada"}

    def step(self, unknown, column="estado", mapping=None):
        return {"op": "replace", "column": column, "map": mapping or self.MAP, "unknown": unknown}

    def test_keep_unknown_is_a_warning_that_policy_must_allow(self):
        source = self.write("estados.csv", self.DATA)
        stopped = self.run_cli(plan_recipe(self.step("keep")), source, expected=2)
        m = self.manifest(stopped)
        self.assertEqual((m["motivo"], m["error"]["codigo"]), ("detenida_por_politica", "advertencias_no_admitidas"))
        allowed = plan_recipe(self.step("keep"), politica={"advertencias_permitidas": ["valor_sin_equivalencia"]})
        summary = self.run_cli(allowed, source, expected=1)
        run = Path(summary["ruta_resultados"]) / "01-paso"
        # "abierta" ya es un destino: válida. "en proceso" y "abierta " (espacio): sin equivalencia, sin aproximar.
        self.assertEqual([r[2] for r in self.rows(run / "resultado.csv")[1:]],
                         ["abierta", "abierta", "abierta", "cerrada", "en proceso", "", "abierta "])
        report = json.loads((run / "report.json").read_text(encoding="utf-8"))
        self.assertEqual([(w["codigo"], w["columna"], w["fila"]) for w in report["advertencias_detalle"]],
                         [("valor_sin_equivalencia", "estado", 6), ("valor_sin_equivalencia", "estado", 8)])
        self.assertEqual([[r[2], r[3], r[4], r[5], r[6]] for r in self.rows(run / "cambios_celdas.csv")[1:]], [
            ["2", "estado", "Abierta", "abierta", "replace"], ["4", "estado", "ABIERTA", "abierta", "replace"],
            ["5", "estado", "Cerrada", "cerrada", "replace"]])

    def test_exclude_unknown_keeps_excluded_rows_and_error_stops_without_tables(self):
        source = self.write("estados.csv", self.DATA)
        summary = self.run_cli(plan_recipe(self.step("exclude")), source)
        run = Path(summary["ruta_resultados"]) / "01-paso"
        self.assertEqual([r[0] for r in self.rows(run / "resultado.csv")[1:]], ["OT1", "OT2", "OT3", "OT4", "OT6"])
        self.assertEqual([r[1:3] + [r[5]] + r[6:] for r in self.rows(run / "excluidas.csv")[1:]], [
            ["replace", "valor sin equivalencia en estado", "6", "OT5", "0042", "en proceso"],
            ["replace", "valor sin equivalencia en estado", "8", "OT7", "0099", "abierta "]])
        invariant = self.manifest(summary)["pasos"][0]["invariantes"][0]
        self.assertEqual((invariant["entrada"], invariant["resultado"], invariant["excluidas"], invariant["cumple"]),
                         (7, 5, 2, True))
        failed = self.run_cli(plan_recipe(self.step("error")), source, expected=2)
        m = self.manifest(failed)
        self.assertEqual((m["motivo"], m["pasos"][0]["estado"]), ("error_de_ejecucion", "fallido"))
        self.assertIn("sin equivalencia en estado", m["error"]["mensaje"])
        self.assertNotIn("en proceso", m["error"]["mensaje"])  # sin valores de celdas
        self.assertFalse((Path(failed["ruta_resultados"]) / "01-paso" / "resultado.csv").exists())

    def test_codes_with_leading_zeros_need_an_explicit_mapping_and_plain_command_warns(self):
        source = self.write("estados.csv", self.DATA)
        # "7" no es "0007": solo se reemplaza lo que el mapa dice, letra por letra.
        recipe = plan_recipe(self.step("keep", "equipo", {"0007": "EQ-7", "7": "EQ-7"}),
                             politica={"advertencias_permitidas": ["valor_sin_equivalencia"]})
        run = Path(self.run_cli(recipe, source, expected=1)["ruta_resultados"]) / "01-paso"
        self.assertEqual([r[1] for r in self.rows(run / "resultado.csv")[1:]],
                         ["EQ-7", "EQ-7", "0012", "0042", "0042", "0099", "0099"])
        plan = self.write("plan.json", {"steps": [self.step("keep")]})
        plain = self.cli_plain("transformar", source, "--plan", plan, expected=1)
        self.assertEqual(plain["advertencias_por_codigo"], {"valor_sin_equivalencia": 2})
        old_style = self.write("plan viejo.json", {"steps": [{"op": "select", "columns": ["orden"]}]})
        detail = json.loads((Path(self.cli_plain("transformar", source, "--plan", old_style)["ruta_resultados"])
                             / "report.json").read_text(encoding="utf-8"))["detalle"]
        self.assertNotIn("advertencias", detail)  # planes anteriores: misma salida que antes

    def test_replace_requires_explicit_policy_and_text_map(self):
        source = self.write("estados.csv", self.DATA)
        for step, text in (({"op": "replace", "column": "estado", "map": self.MAP}, "Parámetros inválidos para replace"),
                           (self.step("ignorar"), "unknown debe ser keep"),
                           ({"op": "replace", "column": "estado", "map": {"x": 1}, "unknown": "keep"}, "de textos")):
            error = self.run_cli(plan_recipe(step), source, expected=2)["errores"][0]
            self.assertEqual((error["codigo"], error["campo"]), ("configuracion_invalida", "plan"))
            self.assertIn(text, error["mensaje"])


class CompletarTests(Base):
    # Entrada: 2 OT1 0007 (area vacía) | 3 OT2 0012 | 4 OT3 "7" | 5 OT4 sin equipo | 6 OT5 0042 Taller | 7 OT6 0007 Mina
    # Referencia: 2 0007 Mina | 3 y 4 0012 (duplicada) | 5 sin clave | 6 0042 Servicios
    ORDENES = "orden;equipo;area\nOT1;0007;\nOT2;0012;Planta\nOT3;7;\nOT4;;\nOT5;0042;Taller\nOT6;0007;Mina\n"
    FLOTA = "equipo;area;modelo\n0007;Mina;CAT 793\n0012;Planta;X\n0012;Planta;Y\n;Taller;Z\n0042;Servicios;W\n"

    def setUp(self):
        super().setUp()
        self.source = self.write("órdenes flota.csv", self.ORDENES)
        self.write("flota.csv", self.FLOTA)

    def recipe(self, **extra):
        step = {"nombre": "enriquecer", "op": "completar", "entrada": "ordenes", "referencia": "flota",
                "clave": ["equipo"], "columnas": ["area", "modelo"], "existentes": "completar_vacios",
                "politica": {"incidencias": "separar"}, **extra}
        return {"version": 1, "entradas": {"ordenes": {"principal": True, **SEMI},
                                           "flota": {"ruta": "flota.csv", **SEMI}},
                "pasos": [{k: v for k, v in step.items() if v is not None}]}

    def test_rows_are_split_never_multiplied_and_present_data_is_kept(self):
        summary = self.run_cli(self.recipe(), self.source, expected=1)
        run = Path(summary["ruta_resultados"]) / "01-enriquecer"
        a, f = str(self.source.resolve()), str((self.folder / "flota.csv").resolve())
        self.assertEqual(self.rows(run / "completadas.csv"), [
            ["orden", "equipo", "area", "modelo"], ["OT1", "0007", "Mina", "CAT 793"],
            ["OT5", "0042", "Taller", "W"], ["OT6", "0007", "Mina", "CAT 793"]])  # Taller presente: no se pisa
        self.assertEqual(self.rows(run / "ambiguas.csv")[1:], [["OT2", "0012", "Planta"]])
        self.assertEqual(self.rows(run / "sin_coincidencia.csv")[1:], [["OT3", "7", ""]])
        self.assertEqual(self.rows(run / "clave_vacia.csv")[1:], [["OT4", "", ""]])
        self.assertEqual([r[:4] for r in self.rows(run / "incidencias.csv")[1:]], [
            ["clave_vacia_en_referencia", "5", "equipo", f], ["clave_duplicada_en_referencia", "3", "equipo", f],
            ["clave_duplicada_en_referencia", "4", "equipo", f], ["coincidencia_ambigua", "3", "equipo", a],
            ["clave_sin_coincidencia", "4", "equipo", a], ["clave_vacia", "5", "equipo", a]])
        self.assertEqual([r[3:] for r in self.rows(run / "completadas_procedencia.csv")[1:]], [["2"], ["6"], ["7"]])
        self.assertEqual(self.rows(run / "ambiguas_procedencia.csv")[1:], [["2", "ordenes", a, "3", "coincidencia_ambigua"]])
        self.assertEqual(self.rows(run / "cambios_celdas.csv")[1:],
                         [["ordenes", a, "2", "area", "", "Mina", "completar (completar_vacios)", ""]])
        step = self.manifest(summary)["pasos"][0]
        self.assertEqual(step["invariantes"][0] | {"regla": ""}, {
            "tipo": "particion", "regla": "", "entrada": 6, "completadas": 3, "sin_coincidencia": 1, "ambiguas": 1,
            "clave_vacia": 1, "cumple": True})
        self.assertEqual({k: step["conteos"][k] for k in ("celdas_completadas", "celdas_presentes_distintas",
                                                          "celdas_reemplazadas", "claves_duplicadas_en_referencia")},
                         {"celdas_completadas": 1, "celdas_presentes_distintas": 1, "celdas_reemplazadas": 0,
                          "claves_duplicadas_en_referencia": 1})

    def test_replace_policy_overwrites_with_log_and_default_policies_are_conservative(self):
        replaced = self.run_cli(self.recipe(existentes="reemplazar"), self.source, expected=1)
        run = Path(replaced["ruta_resultados"]) / "01-enriquecer"
        self.assertEqual([r[2] for r in self.rows(run / "completadas.csv")[1:]], ["Mina", "Servicios", "Mina"])
        self.assertEqual([(r[2], r[4], r[5]) for r in self.rows(run / "cambios_celdas.csv")[1:]],
                         [("2", "", "Mina"), ("6", "Taller", "Servicios")])
        # Sin "existentes", una columna ya presente es un error antes de crear nada.
        preview = self.run_cli(self.recipe(existentes=None), self.source, "--vista-previa", expected=2)
        self.assertEqual(preview["errores"][0]["codigo"], "columnas_incompatibles")
        self.assertIn("existentes", preview["errores"][0]["mensaje"])
        # Sin política: las filas sin completar detienen el flujo y no se publican tablas.
        stopped = self.run_cli(self.recipe(politica=None), self.source, expected=2)
        m = self.manifest(stopped)
        self.assertEqual((m["motivo"], m["pasos"][0]["estado"]), ("detenida_por_politica", "detenido"))
        self.assertFalse((Path(stopped["ruta_resultados"]) / "01-enriquecer" / "completadas.csv").exists())

    def test_composite_key_with_other_names_keeps_text_numbers_dates_and_zeros(self):
        source = self.write("turnos.csv", "equipo;turno;fecha\n0007;A;2026-10-01\n0007;B;03/10/2026\n007;A;2026-10-02\n")
        self.write("capacidades.csv", "codigo;turno;capacidad\n0007;A;1,5\n0007;B;2,0\n")
        recipe = {"version": 1, "entradas": {"t": {"principal": True, **SEMI},
                                             "cap": {"ruta": "capacidades.csv", **SEMI}},
                  "pasos": [{"nombre": "capacidades", "op": "completar", "entrada": "t", "referencia": "cap",
                             "clave": ["equipo", "turno"], "clave_referencia": ["codigo", "turno"],
                             "columnas": ["capacidad"], "politica": {"incidencias": "separar"}}]}
        run = Path(self.run_cli(recipe, source, expected=1)["ruta_resultados"]) / "01-capacidades"
        self.assertEqual(self.rows(run / "completadas.csv"), [["equipo", "turno", "fecha", "capacidad"],
                                                              ["0007", "A", "2026-10-01", "1,5"],
                                                              ["0007", "B", "03/10/2026", "2,0"]])
        self.assertEqual(self.rows(run / "sin_coincidencia.csv")[1:], [["007", "A", "2026-10-02"]])

    def test_invalid_completar_parameters_are_actionable(self):
        bad = self.recipe(clave_referencia=["equipo", "area"], existentes="pisar")
        errors = {(e["codigo"], e["campo"]): e for e in self.run_cli(bad, self.source, expected=2)["errores"]}
        self.assertEqual(set(errors), {("parametro_invalido", "clave_referencia"), ("parametro_invalido", "existentes")})
        self.assertEqual(errors["parametro_invalido", "existentes"]["paso"], "enriquecer")
        self.assertIn("nunca se pisan", errors["parametro_invalido", "existentes"]["sugerencia"])
        key_as_column = self.run_cli(self.recipe(columnas=["equipo"]), self.source, "--vista-previa", expected=2)
        self.assertIn("no pueden ser parte de la clave", key_as_column["errores"][0]["mensaje"])
        self.assertEqual(self.runs(), [])


class DuplicadosTests(Base):
    # 2 y 3: OT1 idénticas | 4 y 5: OT2 distinta fecha y horas (5 más reciente) | 6 y 7: OT3 misma fecha,
    # distintas horas (empate) | 8 y 9: OT4, la 8 sin fecha | 10: OT5 única | 11: sin orden
    DATA = ("orden;equipo;fecha;horas\nOT1;0007;01/10/2026;2,5\nOT1;0007;01/10/2026;2,5\n"
            "OT2;0012;02/10/2026;1,0\nOT2;0012;03/10/2026;1,5\nOT3;0042;05/10/2026;4,0\nOT3;0042;05/10/2026;3,0\n"
            "OT4;0099;;1,0\nOT4;0099;06/10/2026;2,0\nOT5;0007;07/10/2026;0,5\n;0007;08/10/2026;1,0\n")

    def run_policy(self, expected=1, **extra):
        source = self.write("duplicadas.csv", self.DATA)
        step = {"nombre": "dup", "op": "duplicados", "entrada": "ordenes", "clave": ["orden"],
                "opciones": {"date_format": "%d/%m/%Y"}, "politica": {"incidencias": "separar"}, **extra}
        recipe = {"version": 1, "entradas": {"ordenes": {"principal": True, **SEMI}},
                  "pasos": [{k: v for k, v in step.items() if v is not None}]}
        summary = self.run_cli(recipe, source, expected=expected)
        return summary, Path(summary["ruta_resultados"]) / "01-dup"

    def fates(self, run):
        return {name: [r[3] for r in self.rows(run / f"{name}_procedencia.csv")[1:]]
                for name in ("conservadas", "excluidas", "conflictos")}

    def motives(self, run, name):
        return {r[3]: r[4] for r in self.rows(run / f"{name}_procedencia.csv")[1:]}

    def test_identical_rows_vs_contradictory_records_without_policy(self):
        summary, run = self.run_policy()
        self.assertEqual(self.fates(run), {"conservadas": ["2", "10"], "excluidas": ["3"],
                                           "conflictos": ["4", "5", "6", "7", "8", "9", "11"]})
        self.assertEqual(self.motives(run, "excluidas"), {"3": "idéntica a ordenes fila 2"})
        self.assertEqual(self.motives(run, "conflictos"), {
            "4": "misma clave con valores distintos en: fecha, horas", "5": "misma clave con valores distintos en: fecha, horas",
            "6": "misma clave con valores distintos en: horas", "7": "misma clave con valores distintos en: horas",
            "8": "misma clave con valores distintos en: fecha, horas", "9": "misma clave con valores distintos en: fecha, horas",
            "11": "clave vacía: no se puede comparar"})
        self.assertEqual(self.rows(run / "excluidas.csv")[1:], [["OT1", "0007", "01/10/2026", "2,5"]])  # conservada
        step = self.manifest(summary)["pasos"][0]
        self.assertEqual((step["invariantes"][0]["entrada"], step["invariantes"][0]["cumple"]), (10, True))
        self.assertEqual(step["filas"]["excluidas"], 1)
        self.assertEqual(step["incidencias_por_codigo"], {"conflicto_de_duplicados": 6, "clave_vacia": 1})

    def test_most_recent_requires_valid_dates_and_ties_are_conflicts_by_default(self):
        _, run = self.run_policy(conservar="mas_reciente", fecha="fecha")
        self.assertEqual(self.fates(run), {"conservadas": ["2", "5", "10"], "excluidas": ["3", "4"],
                                           "conflictos": ["6", "7", "8", "9", "11"]})
        self.assertEqual(self.motives(run, "excluidas")["4"],
                         "misma clave con valores distintos en: fecha, horas; política mas_reciente: se conservó "
                         "ordenes fila 5")
        self.assertEqual(self.motives(run, "conflictos")["6"], "misma clave con valores distintos en: horas; empate en "
                                                               "la fecha más reciente (fecha)")
        self.assertEqual(self.motives(run, "conflictos")["8"], "misma clave con valores distintos en: fecha, horas; "
                                                               "fecha vacía o inválida en fecha")
        _, run = self.run_policy(conservar="mas_reciente", fecha="fecha", empate="ultimo")
        self.assertEqual(self.fates(run), {"conservadas": ["2", "5", "7", "10"], "excluidas": ["3", "4", "6"],
                                           "conflictos": ["8", "9", "11"]})

    def test_first_last_and_default_stop(self):
        _, run = self.run_policy(conservar="primero")
        self.assertEqual(self.fates(run), {"conservadas": ["2", "4", "6", "8", "10"], "excluidas": ["3", "5", "7", "9"],
                                           "conflictos": ["11"]})
        _, run = self.run_policy(conservar="ultimo")
        self.assertEqual(self.fates(run)["conservadas"], ["2", "5", "7", "9", "10"])
        summary, run = self.run_policy(expected=2, politica=None)
        self.assertEqual(self.manifest(summary)["motivo"], "detenida_por_politica")
        self.assertFalse((run / "conservadas.csv").exists())

    def test_normalization_creates_conflicts_and_copies_from_two_files_are_identical(self):
        self.write("a.csv", "orden;estado\nOT9;abierta\nOT8;x\n")
        self.write("b.csv", "orden;estado\n OT9 ;cerrada\nOT8;x\n")
        recipe = {"version": 1, "entradas": {"a": {"principal": True, **SEMI}, "b": {"ruta": "b.csv", **SEMI}},
                  "pasos": [{"nombre": "union", "op": "consolidar", "entradas": ["a", "b"]},
                            {"nombre": "limpio", "op": "transformar", "entrada": "union.resultado",
                             "plan": {"steps": [{"op": "normalize", "columns": ["orden"]}]}},
                            {"nombre": "dup", "op": "duplicados", "entrada": "limpio.resultado", "clave": ["orden"],
                             "politica": {"incidencias": "separar"}}]}
        run = Path(self.run_cli(recipe, self.folder / "a.csv", expected=1)["ruta_resultados"]) / "03-dup"
        b = str((self.folder / "b.csv").resolve())
        # " OT9 " solo choca con "OT9" tras normalizar: conflicto. OT8 está en los dos archivos: idéntica
        # aunque __archivo_origen difiera (las columnas de procedencia no se comparan por defecto).
        self.assertEqual([r[0] for r in self.rows(run / "conflictos.csv")[1:]], ["OT9", "OT9"])
        self.assertEqual(self.rows(run / "excluidas_procedencia.csv")[1:], [["2", "b", b, "3", "idéntica a a fila 3"]])

    def test_invalid_duplicate_policies(self):
        cases = [({"conservar": "mas_reciente"}, ("parametro_ausente", "fecha")),
                 ({"conservar": "aleatorio"}, ("parametro_invalido", "conservar")),
                 ({"empate": "primero"}, ("parametro_invalido", "empate")),
                 ({"fecha": "fecha"}, ("parametro_invalido", "fecha"))]
        for extra, expected in cases:
            source = self.write("duplicadas.csv", self.DATA)
            recipe = {"version": 1, "entradas": {"ordenes": {"principal": True, **SEMI}},
                      "pasos": [{"nombre": "dup", "op": "duplicados", "entrada": "ordenes", "clave": ["orden"], **extra}]}
            error = self.run_cli(recipe, source, expected=2)["errores"][0]
            self.assertEqual((error["codigo"], error["campo"], error["paso"]), (*expected, "dup"), extra)
        self.assertEqual(self.runs(), [])


if __name__ == "__main__":
    unittest.main()

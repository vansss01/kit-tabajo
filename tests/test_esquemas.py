"""Esquema publicado y validador del kit aceptan y rechazan exactamente lo mismo (etapa 4).

Corpus: todas las reglas, planes y recetas de examples/ y recetas/, configuraciones válidas de las
pruebas y sus casos de error. Un caso que el validador rechaza y el esquema acepta debe declarar
la regla semántica (REGLAS_SEMANTICAS) y el código de error esperado; cualquier otra diferencia falla.
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from esquema_oraculo import valid
from kitlib.esquemas import REGLAS_SEMANTICAS, esquemas
from kitlib.operations import check_plan, validate_config
from kitlib.receta_modelo import RecipeError
from kitlib.receta_validacion import cargar_receta
from kitlib.runtime import configure
from kitlib.tableio import Options, load_config

configure()

PUBLISHED = {name: json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
             for name in ("reglas", "plan", "receta")}
SCHEMAS = json.loads(json.dumps(esquemas()))  # lo que genera el código; PUBLISHED debe ser idéntico
RULES = {"columns": {"orden": {"required": True, "nonempty": True, "unique": True},
                     "horas": {"type": "number", "decimal": ",", "min": "0", "max": "24"}}}
PLAN = {"steps": [{"op": "filter", "column": "estado", "operator": "eq", "value": "abierta"},
                  {"op": "group", "by": ["equipo"], "aggregates": [{"op": "count", "as": "n"},
                                                                   {"op": "sum", "column": "horas", "as": "h"}]}]}
SEMI = {"delimiter": ";", "decimal": ","}


def recipe(*steps, entries=None, **top):
    base = {"version": 1, "entradas": entries or {"ordenes": {"principal": True, **SEMI}},
            "pasos": list(steps) or [{"nombre": "perfil", "op": "inspeccionar", "entrada": "ordenes"}]}
    base.update(top)
    return base


def step(op, nombre="p", **params):
    return {"nombre": nombre, "op": op, **params}


VALID = [  # (tipo, nombre, configuración)
    ("reglas", "reglas pruebas", RULES),
    ("reglas", "unique_keys", {"columns": {}, "unique_keys": [["orden", "equipo"]]}),
    ("plan", "plan pruebas", PLAN),
    ("plan", "todas las operaciones", {"steps": [
        {"op": "select", "columns": ["a", "b"]}, {"op": "sort", "columns": ["a"], "descending": True, "type": "number"},
        {"op": "convert", "column": "h", "type": "number", "decimal": ","}, {"op": "deduplicate", "keys": ["a"]},
        {"op": "rename", "columns": {"a": "b", "b": "a"}}, {"op": "normalize", "columns": ["a"], "case": "upper"},
        {"op": "replace", "column": "e", "map": {"x": "y", "": "vacío"}, "unknown": "exclude"},
        {"op": "filter", "column": "f", "operator": "eq", "value": None},
        {"op": "group", "by": [], "aggregates": [{"op": "count", "as": "n"}]}]}),
    ("plan", "plan vacío", {"steps": []}),
    ("receta", "mínima", recipe()),
    ("receta", "todos los pasos", recipe(
        step("inspeccionar", "perfil", entrada="ordenes", sample=20),
        step("validar", "revision", entrada="ordenes", reglas=RULES, politica={"incidencias": "separar"}),
        step("validar", "revision2", entrada="ordenes", reglas="reglas.json"),
        step("transformar", "resumen", entrada="revision.aceptadas", plan=PLAN, traza="detallada",
             opciones={"decimal": ".", "date_format": "%d/%m/%Y"}),
        step("transformar", "resumen2", entrada="ordenes", plan="plan.json"),
        step("consultar", "sql", tablas={"t": "ordenes", "f": "flota"}, sql="SELECT 1", numeric=["horas"],
             politica={"advertencias_permitidas": ["resultado_depende_de_texto_sin_numeric"]}),
        step("consolidar", "union", entradas=["ordenes", "anterior"]),
        step("comparar", "cambios", antes="anterior", despues="ordenes", clave=["orden"]),
        step("completar", "enriquecer", entrada="ordenes", referencia="flota", clave=["equipo"],
             clave_referencia=["codigo"], columnas=["area"], existentes="completar_vacios"),
        step("duplicados", "dup", entrada="ordenes", clave=["orden"], conservar="mas_reciente", fecha="fecha",
             empate="ultimo", comparar=["horas"]),
        step("exportar", "entrega", tablas={"aceptadas": "revision.aceptadas"}, formatos=["csv", "xlsx"],
             archivo="entrega", safe_csv=True),
        entries={"ordenes": {"principal": True, **SEMI, "fila_encabezado": 2, "encoding": None, "sheet": None,
                             "excluir_filas": [{"columna": "orden", "igual": "TOTAL"},
                                               {"columna": "orden", "empieza_con": "Fin"},
                                               {"columna": "orden", "vacia": True}],
                             "politica": {"incidencias": "separar", "advertencias_permitidas": []}},
                 "anterior": {"ruta": "anterior.csv", "delimiter": "TAB"}, "flota": {"ruta": "flota.csv"}},
        nombre="todo", descripcion="cualquier cosa", salida={"delimiter": ";"})),
]

INVALID = [  # (tipo, nombre, configuración, regla semántica o None si es estructural, código esperado)
    ("reglas", "sin columns", {"unique_keys": []}, None, None),
    ("reglas", "clave desconocida", {"columns": {}, "extra": 1}, None, None),
    ("reglas", "tipo desconocido", {"columns": {"a": {"type": "texto"}}}, None, None),
    ("reglas", "required no booleano", {"columns": {"a": {"required": "si"}}}, None, None),
    ("reglas", "allowed vacío", {"columns": {"a": {"allowed": []}}}, None, None),
    ("reglas", "allowed no textos", {"columns": {"a": {"allowed": [1]}}}, None, None),
    ("reglas", "decimal raro", {"columns": {"a": {"decimal": ";"}}}, None, None),
    ("reglas", "regla no objeto", {"columns": {"a": 3}}, None, None),
    ("reglas", "unique_keys vacía", {"columns": {}, "unique_keys": [[]]}, None, None),
    ("reglas", "límite vacío", {"columns": {"a": {"type": "number", "min": " "}}}, None, None),
    ("reglas", "rango en texto", {"columns": {"a": {"type": "string", "min": "1"}}}, "reglas_rangos", None),
    ("reglas", "rango sin tipo", {"columns": {"a": {"max": "1"}}}, "reglas_rangos", None),
    ("reglas", "min mayor que max", {"columns": {"a": {"type": "number", "min": "5", "max": "1"}}}, "reglas_rangos", None),
    ("reglas", "límite no numérico", {"columns": {"a": {"type": "number", "min": "abc"}}}, "reglas_rangos", None),
    ("plan", "sin steps", {}, None, None),
    ("plan", "steps no lista", {"steps": {}}, None, None),
    ("plan", "operación desconocida", {"steps": [{"op": "eval"}]}, None, None),
    ("plan", "parámetro extra", {"steps": [{"op": "select", "columns": ["a"], "x": 1}]}, None, None),
    ("plan", "operador raro", {"steps": [{"op": "filter", "column": "a", "operator": "like", "value": "x"}]}, None, None),
    ("plan", "value lista", {"steps": [{"op": "filter", "column": "a", "operator": "eq", "value": [1]}]}, None, None),
    ("plan", "convert column no texto", {"steps": [{"op": "convert", "column": 5, "type": "number"}]}, None, None),
    ("plan", "date_format no texto", {"steps": [{"op": "convert", "column": "a", "type": "date",
                                                  "date_format": 5}]}, None, None),
    ("plan", "agregados vacíos", {"steps": [{"op": "group", "by": ["e"], "aggregates": []}]}, None, None),
    ("plan", "agregado column no texto", {"steps": [{"op": "group", "by": [], "aggregates": [
        {"op": "count", "column": 3, "as": "n"}]}]}, None, None),
    ("plan", "columnas repetidas", {"steps": [{"op": "select", "columns": ["a", "a"]}]}, None, None),
    ("plan", "rename vacío", {"steps": [{"op": "rename", "columns": {}}]}, None, None),
    ("plan", "rename a espacio", {"steps": [{"op": "rename", "columns": {"a": " "}}]}, None, None),
    ("plan", "case raro", {"steps": [{"op": "normalize", "columns": ["a"], "case": "title"}]}, None, None),
    ("plan", "normalize sin columnas", {"steps": [{"op": "normalize", "columns": []}]}, None, None),
    ("plan", "replace sin unknown", {"steps": [{"op": "replace", "column": "a", "map": {"x": "y"}}]}, None, None),
    ("plan", "replace unknown raro", {"steps": [{"op": "replace", "column": "a", "map": {"x": "y"},
                                                  "unknown": "ignorar"}]}, None, None),
    ("plan", "replace map no texto", {"steps": [{"op": "replace", "column": "a", "map": {"x": 1},
                                                  "unknown": "keep"}]}, None, None),
    ("plan", "descending no booleano", {"steps": [{"op": "sort", "columns": ["a"], "descending": "si"}]}, None, None),
    ("plan", "rename dos destinos iguales", {"steps": [{"op": "rename", "columns": {"a": "x", "b": "x"}}]},
     "plan_relacionados", None),
    ("plan", "contains numérico", {"steps": [{"op": "filter", "column": "a", "operator": "contains", "value": "1",
                                               "type": "number"}]}, "plan_relacionados", None),
    ("plan", "sum sin column", {"steps": [{"op": "group", "by": [], "aggregates": [{"op": "sum", "as": "s"}]}]},
     "plan_relacionados", None),
    ("plan", "alias repetido", {"steps": [{"op": "group", "by": ["e"], "aggregates": [{"op": "count", "as": "e"}]}]},
     "plan_relacionados", None),
    ("receta", "versión 2", recipe(version=2), None, "version_no_admitida"),
    ("receta", "versión true", recipe(version=True), None, "version_no_admitida"),
    ("receta", "sin versión", {k: v for k, v in recipe().items() if k != "version"}, None, "version_ausente"),
    ("receta", "campo extra", recipe(extra=True), None, "campo_desconocido"),
    ("receta", "decimal punto y coma", recipe(entries={"ordenes": {"principal": True, "decimal": ";"}}), None,
     "opcion_invalida"),
    ("receta", "delimitador largo", recipe(entries={"ordenes": {"principal": True, "delimiter": ";;"}}), None,
     "opcion_invalida"),
    ("receta", "operación con errata", recipe(step("inspecionar", entrada="ordenes")), None, "operacion_desconocida"),
    ("receta", "parámetro desconocido", recipe(step("inspeccionar", entrada="ordenes", x=1)), None,
     "parametro_desconocido"),
    ("receta", "parámetro ausente", recipe(step("validar", entrada="ordenes")), None, "parametro_ausente"),
    ("receta", "política rara", recipe(step("inspeccionar", entrada="ordenes", politica={"incidencias": "ignorar"})),
     None, "politica_invalida"),
    ("receta", "separar en comparar", recipe(step("comparar", antes="ordenes", despues="ordenes", clave=["o"],
                                                  politica={"incidencias": "separar"})), None, "politica_no_aplicable"),
    ("receta", "advertencia con comodín", recipe(step("inspeccionar", entrada="ordenes",
                                                      politica={"advertencias_permitidas": ["*"]})), None,
     "politica_invalida"),
    ("receta", "formato pdf", recipe(step("exportar", tablas={"o": "ordenes"}, formatos=["pdf"])), None,
     "parametro_invalido"),
    ("receta", "hoja reservada", recipe(step("exportar", tablas={"report": "ordenes"})), None, "nombre_invalido"),
    ("receta", "sample 25", recipe(step("inspeccionar", entrada="ordenes", sample=25)), None, "parametro_invalido"),
    ("receta", "traza rara", recipe(step("transformar", entrada="ordenes", plan=PLAN, traza="x")), None,
     "parametro_invalido"),
    ("receta", "plan inline inválido", recipe(step("transformar", entrada="ordenes", plan={"steps": [
        {"op": "group", "by": ["e"], "aggregates": []}]})), None, "configuracion_invalida"),
    ("receta", "reglas inline inválidas", recipe(step("validar", entrada="ordenes", reglas={"columns": {
        "a": {"type": "x"}}})), None, "configuracion_invalida"),
    ("receta", "existentes pisar", recipe(step("completar", entrada="ordenes", referencia="flota", clave=["e"],
                                               columnas=["a"], existentes="pisar"),
                                          entries={"ordenes": {"principal": True}, "flota": {"ruta": "flota.csv"}}),
     None, "parametro_invalido"),
    ("receta", "conservar aleatorio", recipe(step("duplicados", entrada="ordenes", clave=["o"], conservar="aleatorio")),
     None, "parametro_invalido"),
    ("receta", "fila_encabezado 0", recipe(entries={"ordenes": {"principal": True, "fila_encabezado": 0}}), None,
     "parametro_invalido"),
    ("receta", "condición doble", recipe(entries={"ordenes": {"principal": True, "excluir_filas": [
        {"columna": "o", "igual": "T", "vacia": True}]}}), None, "parametro_invalido"),
    ("receta", "condición contiene", recipe(entries={"ordenes": {"principal": True, "excluir_filas": [
        {"columna": "o", "contiene": "T"}]}}), None, "parametro_invalido"),
    ("receta", "condiciones vacías", recipe(entries={"ordenes": {"principal": True, "excluir_filas": []}}), None,
     "parametro_invalido"),
    ("receta", "nombre de paso inválido", recipe(step("inspeccionar", "Perfil", entrada="ordenes")), None,
     "nombre_invalido"),
    ("receta", "referencia vacía", recipe(step("inspeccionar", entrada="")), None, "referencia_invalida"),
    ("receta", "sin pasos", recipe() | {"pasos": []}, None, "pasos_ausentes"),
    ("receta", "referencia adelantada", recipe(step("inspeccionar", "a", entrada="b.resultado"),
                                               step("transformar", "b", entrada="ordenes", plan=PLAN)),
     "referencias", "referencia_adelantada"),
    ("receta", "salida inexistente", recipe(step("validar", "v", entrada="ordenes", reglas=RULES),
                                            step("inspeccionar", "i", entrada="v.aceptada")),
     "referencias", "salida_inexistente"),
    ("receta", "referencia inexistente", recipe(step("inspeccionar", entrada="nada")), "referencias",
     "referencia_inexistente"),
    ("receta", "paso con nombre de entrada", recipe(step("inspeccionar", "ordenes", entrada="ordenes")),
     "nombres_unicos", "nombre_duplicado"),
    ("receta", "entrada sin uso", recipe(entries={"ordenes": {"principal": True}, "flota": {"ruta": "flota.csv"}}),
     "entradas", "entrada_sin_uso"),
    ("receta", "dos principales", recipe(step("consolidar", entradas=["ordenes", "flota"]),
                                         entries={"ordenes": {"principal": True}, "flota": {"principal": True}}),
     "entradas", "principal_ambigua"),
    ("receta", "archivo inexistente", recipe(step("consolidar", entradas=["ordenes", "flota"]),
                                             entries={"ordenes": {"principal": True}, "flota": {"ruta": "no.csv"}}),
     "entradas", "archivo_no_encontrado"),
    ("receta", "plan en ruta inexistente", recipe(step("transformar", entrada="ordenes", plan="no.json")),
     "archivos_de_configuracion", "archivo_no_encontrado"),
    ("receta", "clave_referencia de otro largo", recipe(
        step("completar", entrada="ordenes", referencia="flota", clave=["e"], clave_referencia=["a", "b"],
             columnas=["c"]), entries={"ordenes": {"principal": True}, "flota": {"ruta": "flota.csv"}}),
     "parametros_relacionados", "parametro_invalido"),
    ("receta", "mas_reciente sin fecha", recipe(step("duplicados", entrada="ordenes", clave=["o"],
                                                     conservar="mas_reciente")),
     "parametros_relacionados", "parametro_ausente"),
    ("receta", "empate sin mas_reciente", recipe(step("duplicados", entrada="ordenes", clave=["o"], empate="primero")),
     "parametros_relacionados", "parametro_invalido"),
    ("receta", "fecha sin mas_reciente", recipe(step("duplicados", entrada="ordenes", clave=["o"], fecha="f")),
     "parametros_relacionados", "parametro_invalido"),
]


class EquivalenciaTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="esquemas-", dir=ROOT / "tmp")
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        for name in ("principal.csv", "anterior.csv", "flota.csv"):
            (self.folder / name).write_text("orden;equipo\nOT1;0007\n", encoding="utf-8")
        (self.folder / "reglas.json").write_text(json.dumps(RULES), encoding="utf-8")
        (self.folder / "plan.json").write_text(json.dumps(PLAN), encoding="utf-8")

    def validator(self, kind, config, path=None):
        """(acepta, códigos de error) según la validación real del kit."""
        try:
            if kind == "reglas":
                validate_config(config, Options())
            elif kind == "plan":
                check_plan(config, Options())
            else:
                if path is None:
                    path = self.folder / "receta.json"
                    path.write_text(json.dumps(config), encoding="utf-8")
                cargar_receta(path, self.folder / "principal.csv")
        except RecipeError as exc:
            return False, {e["codigo"] for e in exc.errors}
        except ValueError:
            return False, set()
        return True, set()

    def test_published_schemas_are_generated_from_code(self):
        self.assertEqual(PUBLISHED, SCHEMAS, "Ejecute python -B scripts/esquemas.py")

    def test_examples_and_valid_cases_pass_both(self):
        files = ([("reglas", p) for p in sorted((ROOT / "examples").rglob("reglas*.json"))]
                 + [("plan", p) for p in sorted((ROOT / "examples").rglob("plan*.json"))]
                 + [("receta", p) for p in sorted((ROOT / "recetas").glob("*.json"))])
        self.assertGreaterEqual(len(files), 6)
        for kind, path in files:
            config = load_config(path)
            self.assertTrue(valid(config, SCHEMAS[kind]), path)
            self.assertEqual(self.validator(kind, config, path if kind == "receta" else None), (True, set()), path)
        for kind, name, config in VALID:
            self.assertTrue(valid(config, SCHEMAS[kind]), name)
            self.assertEqual(self.validator(kind, config), (True, set()), name)

    def test_invalid_cases_are_rejected_by_both_or_are_listed_semantic_rules(self):
        for kind, name, config, semantic, code in INVALID:
            accepted, codes = self.validator(kind, copy.deepcopy(config))
            self.assertFalse(accepted, f"{kind} {name}: el validador lo acepta")
            if code:
                self.assertIn(code, codes, f"{kind} {name}")
            if semantic is None:
                self.assertFalse(valid(config, SCHEMAS[kind]), f"{kind} {name}: el esquema lo acepta")
            else:
                self.assertIn(semantic, REGLAS_SEMANTICAS)
                self.assertTrue(valid(config, SCHEMAS[kind]), f"{kind} {name}: debería ser solo semántico")

    def test_semantic_rules_are_documented(self):
        doc = (ROOT / "docs" / "ESQUEMAS.md").read_text(encoding="utf-8")
        for rule in REGLAS_SEMANTICAS:
            self.assertIn(f"`{rule}`", doc)
        used = {semantic for *_, semantic, _ in INVALID if semantic}
        self.assertEqual(used, set(REGLAS_SEMANTICAS) - {"clave_json_repetida", "columnas"})  # estas dos: abajo
        # clave_json_repetida no llega al esquema (se decide al leer); columnas necesita los datos.

    def test_oracle_is_not_trivial(self):
        # El intérprete distingue de verdad (si aceptara todo, las pruebas de arriba no valdrían nada).
        schema = {"type": "object", "required": ["a"], "additionalProperties": False,
                  "properties": {"a": {"type": "integer", "minimum": 1}}}
        self.assertTrue(valid({"a": 2}, schema))
        bad_values: list = [{}, {"a": 0}, {"a": True}, {"a": 1, "b": 2}, []]
        for bad in bad_values:
            self.assertFalse(valid(bad, schema), bad)
        with self.assertRaises(AssertionError):
            valid(1, {"format": "date"})


if __name__ == "__main__":
    unittest.main()

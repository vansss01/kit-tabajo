"""Esquemas JSON (draft 2020-12) de reglas, planes y recetas, generados desde las mismas tablas
de definiciones que usa la validación (operations.py y receta_modelo.py).

Por qué así: la validación ya existe, con mensajes y códigos estables; generar el esquema desde sus
tablas evita una segunda lista de lo admitido. tests/test_esquemas.py comprueba sobre un corpus que
esquema y validador aceptan y rechazan lo mismo, salvo las REGLAS_SEMANTICAS listadas aquí.
Publicados en schemas/*.schema.json (`python -B scripts/esquemas.py` los regenera).
"""
from kitlib.operations import (AGGREGATES, CASES, DECIMALS, FILTER_OPERATORS, RULE_KEYS, SCHEMAS, SQL_TYPES, TYPES,
                               UNKNOWN_VALUES)
from kitlib.receta_modelo import (CODE, COMMON, CONSERVAR, EMPATE, ENTRY_KEYS, EXCLUSION_TESTS, EXISTENTES,
                                  FORMATS, INCIDENCIAS, NAME, PARAMS, READ_OPTIONS, RESERVED, SAMPLE_MAX,
                                  SEPARABLE, SQL_NAME, TOP_KEYS, TRAZA, VERSION)

SCHEMA_VERSION = 1  # cambia si cambia lo que se admite; las recetas declaran su propia "version"
DRAFT = "https://json-schema.org/draft/2020-12/schema"


def _pattern(regex):
    return "^" + regex.pattern + "$"


TEXT = {"type": "string", "pattern": r"\S"}          # texto con algún carácter visible
NONEMPTY = {"type": "string", "minLength": 1}
COLUMNS = {"type": "array", "minItems": 1, "uniqueItems": True, "items": NONEMPTY}
REF = NONEMPTY                                         # entrada o "paso.salida"
DELIMITER = {"type": "string", "pattern": '^(TAB|[^\r\n"])$'}
DECIMAL = {"enum": list(DECIMALS)}

# Reglas que un esquema JSON no puede expresar: dónde se comprueban y con qué código de error.
REGLAS_SEMANTICAS = {
    "clave_json_repetida": ("Una clave repetida en un mismo objeto JSON (se decide al leer el JSON, antes del "
                            "esquema)", "tableio.unique_keys", "clave_json_repetida / configuracion_invalida"),
    "referencias": ("Cada referencia nombra una entrada o una salida de un paso anterior",
                    "receta_validacion.cargar_receta", "referencia_inexistente, referencia_adelantada, salida_inexistente"),
    "nombres_unicos": ("Pasos y entradas con nombres distintos entre sí", "receta_validacion.cargar_receta",
                       "nombre_duplicado"),
    "entradas": ("Exactamente una entrada principal, todas usadas, con archivo existente; fila_encabezado y "
                 "excluir_filas solo para CSV/XLSX", "receta_validacion.cargar_receta",
                 "principal_ambigua, entrada_sin_uso, entrada_sin_ruta, entrada_desconocida, archivo_no_encontrado, "
                 "parametro_invalido"),
    "archivos_de_configuracion": ("reglas o plan dados como ruta: existir y ser válidos",
                                  "receta_validacion._config", "archivo_no_encontrado, configuracion_invalida"),
    "parametros_relacionados": ("completar: clave y clave_referencia del mismo largo; duplicados: fecha solo y "
                                "siempre con mas_reciente, empate solo con mas_reciente; consultar: tipos solo "
                                "de tablas presentes en tablas",
                                "receta_validacion.cargar_receta", "parametro_invalido, parametro_ausente"),
    "plan_relacionados": ("filter contains requiere type string; sum/mean/min/max requieren column; alias de "
                          "agregado únicos y distintos de by; rename sin dos destinos iguales",
                          "operations.check_step", "configuracion_invalida"),
    "reglas_rangos": ("min/max solo con type number, integer o date; convertibles con el decimal y formato de la "
                      "regla; min no mayor que max", "operations.validate_config", "configuracion_invalida"),
    "columnas": ("Columnas usadas por planes, claves, SQL y condiciones existen en los encabezados",
                 "receta_vista.comprobar_columnas (vista previa y antes de ejecutar)",
                 "columnas_incompatibles, encabezado_ilegible"),
}


def reglas_schema():
    properties = {
        "required": {"type": "boolean"}, "nonempty": {"type": "boolean"}, "unique": {"type": "boolean"},
        "type": {"enum": sorted(TYPES)}, "min": {"type": ["string", "number"], "pattern": r"\S"},
        "max": {"type": ["string", "number"], "pattern": r"\S"}, "date_format": {"type": "string"},
        "decimal": DECIMAL, "allowed": {"type": "array", "minItems": 1, "items": {"type": "string"}}}
    assert set(properties) == set(RULE_KEYS)
    rule = {"type": "object", "additionalProperties": False, "properties": properties}
    return {"type": "object", "required": ["columns"], "additionalProperties": False, "properties": {
        "columns": {"type": "object", "additionalProperties": rule},
        "unique_keys": {"type": "array", "items": {"type": "array", "minItems": 1, "items": {"type": "string"}}}}}


def _plan_field(op, key):
    fields = {
        "columns": COLUMNS, "keys": COLUMNS, "column": {"type": "string"}, "operator": {"enum": list(FILTER_OPERATORS)},
        "value": {"type": ["string", "number", "boolean", "null"]}, "type": {"enum": sorted(TYPES)},
        "decimal": DECIMAL, "date_format": {"type": "string"}, "descending": {"type": "boolean"},
        "by": {"type": "array", "uniqueItems": True, "items": NONEMPTY},
        "aggregates": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["op", "as"], "additionalProperties": False,
            "properties": {"op": {"enum": list(AGGREGATES)}, "column": {"type": "string"}, "as": TEXT}}},
        "case": {"enum": list(CASES)},
        "map": {"type": "object", "minProperties": 1, "additionalProperties": {"type": "string"}},
        "unknown": {"enum": list(UNKNOWN_VALUES)}}
    if op == "rename" and key == "columns":
        return {"type": "object", "minProperties": 1, "propertyNames": {"minLength": 1}, "additionalProperties": TEXT}
    if op == "replace" and key == "column":
        return NONEMPTY
    return fields[key]


def plan_schema():
    steps = []
    for op, (allowed, required) in SCHEMAS.items():
        props = {k: ({"const": op} if k == "op" else _plan_field(op, k)) for k in sorted(allowed)}
        steps.append({"type": "object", "required": sorted(required | {"op"}), "additionalProperties": False,
                      "properties": props})
    return {"type": "object", "required": ["steps"], "additionalProperties": False,
            "properties": {"steps": {"type": "array", "items": {"oneOf": steps}}}}


def _policy(separable):
    return {"type": "object", "additionalProperties": False, "properties": {
        "incidencias": {"enum": list(INCIDENCIAS) if separable else ["detener"]},
        "advertencias_permitidas": {"type": "array", "items": {"type": "string", "pattern": _pattern(CODE)}}}}


def _recipe_field(op, key):
    table_map = {"type": "object", "minProperties": 1, "additionalProperties": REF}
    fields = {
        "entrada": REF, "referencia": REF, "antes": REF, "despues": REF, "fecha": NONEMPTY,
        "sample": {"type": "integer", "minimum": 0, "maximum": SAMPLE_MAX},
        "reglas": {"oneOf": [{"$ref": "#/$defs/reglas"}, NONEMPTY]},
        "plan": {"oneOf": [{"$ref": "#/$defs/plan"}, NONEMPTY]}, "traza": {"enum": list(TRAZA)},
        "sql": TEXT, "numeric": {"type": "array", "items": NONEMPTY},
        "tipos": {"type": "object", "propertyNames": {"pattern": _pattern(SQL_NAME)}, "additionalProperties": {
            "type": "object", "minProperties": 1, "propertyNames": {"minLength": 1},
            "additionalProperties": {"enum": list(SQL_TYPES)}}},
        "detector": {"type": "boolean"}, "detector_max_filas": {"type": "integer", "minimum": 1},
        "entradas": {"type": "array", "minItems": 1, "items": REF},
        "clave": COLUMNS, "clave_referencia": COLUMNS, "columnas": COLUMNS, "comparar": COLUMNS,
        "formatos": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"enum": sorted(FORMATS)}},
        "archivo": {"type": "string", "pattern": _pattern(NAME), "not": {"enum": sorted(RESERVED)}},
        "safe_csv": {"type": "boolean"}, "existentes": {"enum": list(EXISTENTES)},
        "conservar": {"enum": list(CONSERVAR)}, "empate": {"enum": list(EMPATE)}}
    if key == "tablas":
        names = ({"pattern": _pattern(SQL_NAME)} if op == "consultar"
                 else {"pattern": _pattern(NAME), "not": {"enum": sorted(RESERVED)}})
        return {**table_map, "propertyNames": names}
    return fields[key]


def receta_schema():
    exclusion = [{"type": "object", "required": ["columna", test], "additionalProperties": False,
                  "properties": {"columna": {"type": "string"},
                                 test: {"const": True} if test == "vacia" else
                                 NONEMPTY if test == "empieza_con" else {"type": "string"}}}
                 for test in EXCLUSION_TESTS]
    entry_props = {"ruta": NONEMPTY, "principal": {"type": "boolean"}, "politica": _policy(True), "descripcion": {},
                   "delimiter": DELIMITER, "decimal": DECIMAL, "encoding": {"type": ["string", "null"]},
                   "date_format": {"type": ["string", "null"]}, "sheet": {"type": ["string", "null"]},
                   "fila_encabezado": {"type": "integer", "minimum": 1},
                   "excluir_filas": {"type": "array", "minItems": 1, "items": {"oneOf": exclusion}}}
    assert set(entry_props) == ENTRY_KEYS and READ_OPTIONS <= set(entry_props)
    steps = []
    for op, (allowed, required) in PARAMS.items():
        props = {"nombre": {"type": "string", "pattern": _pattern(NAME)}, "op": {"const": op}, "descripcion": {},
                 "opciones": {"type": "object", "additionalProperties": False,
                              "properties": {"decimal": DECIMAL, "date_format": {"type": ["string", "null"]}}},
                 "politica": _policy(op in SEPARABLE)}
        assert set(props) == COMMON
        props.update({k: _recipe_field(op, k) for k in sorted(allowed)})
        steps.append({"type": "object", "required": sorted(required | {"nombre", "op"}),
                      "additionalProperties": False, "properties": props})
    top = {"version": {"const": VERSION}, "nombre": TEXT, "descripcion": {},
           "entradas": {"type": "object", "minProperties": 1, "propertyNames": {"pattern": _pattern(NAME)},
                        "additionalProperties": {"type": "object", "additionalProperties": False,
                                                 "properties": entry_props}},
           "pasos": {"type": "array", "minItems": 1, "items": {"oneOf": steps}},
           "salida": {"type": "object", "additionalProperties": False, "properties": {"delimiter": DELIMITER}}}
    assert set(top) == TOP_KEYS
    return {"type": "object", "required": ["version", "entradas", "pasos"], "additionalProperties": False,
            "properties": top, "$defs": {"reglas": reglas_schema(), "plan": plan_schema()}}


def esquemas():
    """Los tres esquemas publicados, con identificador y versión."""
    out = {}
    for name, build, title in (("reglas", reglas_schema, "Reglas de validar"),
                               ("plan", plan_schema, "Plan de transformar"),
                               ("receta", receta_schema, "Receta de ejecutar")):
        out[name] = {"$schema": DRAFT, "$id": f"kit-tabajo/{name}.schema.json", "title": title,
                     "x-version-esquema": SCHEMA_VERSION,
                     "$comment": "Generado desde el código (src/kitlib/esquemas.py); no editar a mano. "
                                 "Reglas que el esquema no expresa: REGLAS_SEMANTICAS en esquemas.py y "
                                 "docs/ESQUEMAS.md. Claves JSON repetidas son error.", **build()}
    return out

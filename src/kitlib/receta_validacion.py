"""Comprobación completa de una receta sin leer datos: estructura, operaciones, parámetros,
referencias entre pasos, reglas y planes. Lanza RecipeError con todos los errores."""
import difflib
import json
from dataclasses import replace
from pathlib import Path

from kitlib.operations import DECIMALS, SQL_TYPES, check_plan, validate_config
from kitlib.receta_modelo import (CODE, COMMON, CONSERVAR, EMPATE, ENTRY_KEYS, EXCLUSION_TESTS, EXISTENTES,
                                  FORMATS, INCIDENCIAS, NAME, OUTPUTS, PARAMS, READ_OPTIONS, RESERVED,
                                  SAMPLE_MAX, SEPARABLE, SQL_NAME, TOP_KEYS, TRAZA, VERSION, Entry, Recipe,
                                  RecipeError, Step, _flat, error)
from kitlib.tableio import Options, load_config, unique_keys


# --------------------------------------------------------------------------- validación

def _options(spec, where, errors, step=None):
    opts = Options()
    for key in READ_OPTIONS & set(spec):
        value = spec[key]
        if value is not None and not isinstance(value, str):
            errors.append(error("opcion_invalida", f"{key} debe ser texto", step, f"{where}.{key}"))
            continue
        if key == "delimiter":
            value = "\t" if value == "TAB" else value
            if value is None or len(value) != 1 or value in '\r\n"':
                errors.append(error("opcion_invalida", "delimiter requiere un carácter", step, f"{where}.delimiter",
                                    "Use por ejemplo \";\" o \"TAB\""))
                continue
        if key == "decimal" and value not in DECIMALS:
            errors.append(error("opcion_invalida", "decimal debe ser \".\" o \",\"", step, f"{where}.decimal"))
            continue
        if key == "encoding" and not value:
            continue
        opts = replace(opts, **{key: value})
    return opts


def _policy(spec, where, errors, step=None, separable=True):
    policy = spec.get("politica", {})
    if not isinstance(policy, dict) or set(policy) - {"incidencias", "advertencias_permitidas"}:
        errors.append(error("politica_invalida", "politica admite incidencias y advertencias_permitidas", step,
                            f"{where}.politica"))
        return "detener", set()
    mode = policy.get("incidencias", "detener")
    if mode not in INCIDENCIAS:
        errors.append(error("politica_invalida", "incidencias debe ser \"detener\" o \"separar\"", step,
                            f"{where}.politica.incidencias"))
        mode = "detener"
    elif mode == "separar" and not separable:
        errors.append(error("politica_no_aplicable", "Esta operación no puede separar filas: sus incidencias "
                            "bloquean el resultado completo", step, f"{where}.politica.incidencias",
                            "Use \"detener\" o valide antes con un paso validar"))
        mode = "detener"
    allowed = policy.get("advertencias_permitidas", [])
    if not isinstance(allowed, list) or not all(isinstance(c, str) and CODE.fullmatch(c) for c in allowed):
        errors.append(error("politica_invalida", "advertencias_permitidas: lista de códigos concretos", step,
                            f"{where}.politica.advertencias_permitidas",
                            "Ejemplo: [\"valores_no_numericos_cargados_como_null\"]; no hay comodines"))
        allowed = []
    return mode, set(allowed)


def _config(value, base, step, campo, errors):
    """Reglas o plan: objeto en la receta o ruta a un JSON relativa a la receta."""
    if isinstance(value, dict):
        return value, None
    if isinstance(value, str) and value:
        path = (base / value).resolve()
        if not path.is_file():
            errors.append(error("archivo_no_encontrado", f"No existe {value}", step, campo,
                                "Las rutas de la receta son relativas a la carpeta de la receta"))
            return None, None
        try:
            return load_config(path), path
        except (ValueError, UnicodeError) as exc:
            errors.append(error("configuracion_invalida", f"{value}: JSON inválido ({str(exc)[:80]})", step, campo))
            return None, None
    errors.append(error("parametro_invalido", f"{campo} debe ser un objeto JSON o una ruta", step, campo))
    return None, None


def cargar_receta(path, principal=None, overrides=None, principal_opcional=False):
    """Comprueba y resuelve una receta sin leer datos. Lanza RecipeError con todos los errores."""
    path = Path(path).resolve()
    base = path.parent
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    except FileNotFoundError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RecipeError([error("receta_json_invalido", "La receta no es JSON UTF-8 válido: " + str(exc)[:120])]) from exc
    except ValueError as exc:  # unique_keys
        raise RecipeError([error("clave_json_repetida", str(exc)[:160], None, None,
                                 "Cada nombre puede aparecer una sola vez en un mismo objeto")]) from exc
    errors: list[dict] = []
    if not isinstance(raw, dict):
        raise RecipeError([error("receta_invalida", "La receta debe ser un objeto JSON")])
    for key in sorted(set(raw) - TOP_KEYS):
        errors.append(error("campo_desconocido", f"Campo desconocido: {key}", None, key,
                            _near(key, TOP_KEYS)))
    if "version" not in raw:
        errors.append(error("version_ausente", "Falta \"version\"", None, "version", f"Añada \"version\": {VERSION}"))
    elif raw["version"] != VERSION or isinstance(raw["version"], bool):
        errors.append(error("version_no_admitida", f"Versión de receta no admitida: {str(raw['version'])[:20]}",
                            None, "version", f"Esta versión del kit lee recetas \"version\": {VERSION}"))
    nombre = raw.get("nombre", path.stem)
    if not isinstance(nombre, str) or not nombre.strip():
        errors.append(error("parametro_invalido", "nombre debe ser texto", None, "nombre"))
        nombre = path.stem

    # Entradas
    entries: dict[str, Entry] = {}
    raw_entries = raw.get("entradas")
    if not isinstance(raw_entries, dict) or not raw_entries:
        errors.append(error("entradas_ausentes", "entradas debe ser un objeto con al menos una entrada", None,
                            "entradas", "Ejemplo: \"entradas\": {\"ordenes\": {\"principal\": true}}"))
        raw_entries = {}
    principals = []
    overrides = dict(overrides or {})
    for name, spec in raw_entries.items():
        where = f"entradas.{name}"
        if not NAME.fullmatch(name):
            errors.append(error("nombre_invalido", "Nombres: minúsculas, dígitos y _, empezando por letra",
                                None, where))
            continue
        if not isinstance(spec, dict):
            errors.append(error("parametro_invalido", "Cada entrada es un objeto", None, where))
            continue
        for key in sorted(set(spec) - ENTRY_KEYS):
            errors.append(error("campo_desconocido", f"Campo desconocido: {key}", None, f"{where}.{key}",
                                _near(key, ENTRY_KEYS)))
        if not isinstance(spec.get("principal", False), bool):
            errors.append(error("parametro_invalido", "principal debe ser true o false", None, f"{where}.principal"))
        if spec.get("principal") is True:
            principals.append(name)
        mode, allowed = _policy(spec, where, errors)
        route = None
        if name in overrides:
            route = Path(overrides.pop(name)).resolve()
        elif "ruta" in spec:
            if not isinstance(spec["ruta"], str) or not spec["ruta"]:
                errors.append(error("parametro_invalido", "ruta debe ser texto", None, f"{where}.ruta"))
            else:
                route = (base / spec["ruta"]).resolve()
        entries[name] = Entry(name, route, _layout(spec, where, errors, _options(spec, where, errors)),
                              mode, allowed)
    if len(raw_entries) == 1 and not principals:
        principals = list(raw_entries)
    if len(principals) != 1:
        errors.append(error("principal_ambigua", "Debe haber exactamente una entrada con \"principal\": true",
                            None, "entradas", "La principal recibe el archivo indicado en la línea de comandos"))
    elif principal is not None and principals[0] in entries:
        entries[principals[0]].ruta = Path(principal).resolve()
    for name in sorted(overrides):
        errors.append(error("entrada_desconocida", f"--entrada {name}: la receta no tiene esa entrada", None,
                            "--entrada", _near(name, entries)))
    for entry in entries.values():
        if entry.ruta is None and principal_opcional and len(principals) == 1 and entry.nombre == principals[0]:
            continue  # comprobar sin datos: el archivo principal se indica al ejecutar
        if entry.ruta is None:
            errors.append(error("entrada_sin_ruta", "La entrada no tiene archivo", None, f"entradas.{entry.nombre}",
                                f"Añada \"ruta\" o use --entrada {entry.nombre}=ARCHIVO"))
        elif entry.ruta.suffix.lower() == ".json" and (entry.opts.header_row != 1 or entry.opts.exclude_rows):
            errors.append(error("parametro_invalido", "fila_encabezado y excluir_filas solo se aplican a CSV y XLSX",
                                None, f"entradas.{entry.nombre}", "Una tabla JSON del kit ya no tiene títulos ni pies"))
        elif not entry.ruta.is_file():
            errors.append(error("archivo_no_encontrado", f"No existe el archivo de la entrada {entry.nombre}", None,
                                f"entradas.{entry.nombre}", "Revise la ruta; las de la receta son relativas a ella"))

    # Salida
    salida = raw.get("salida", {})
    delimiter = entries[principals[0]].opts.delimiter if len(principals) == 1 and principals[0] in entries else ","
    if not isinstance(salida, dict) or set(salida) - {"delimiter"}:
        errors.append(error("parametro_invalido", "salida admite solo delimiter", None, "salida"))
    elif "delimiter" in salida:
        delimiter = _options({"delimiter": salida["delimiter"]}, "salida", errors).delimiter

    # Pasos
    steps: list[Step] = []
    configs: list[Path] = []
    raw_steps = raw.get("pasos")
    if not isinstance(raw_steps, list) or not raw_steps:
        errors.append(error("pasos_ausentes", "pasos debe ser una lista no vacía", None, "pasos"))
        raw_steps = []
    available: dict[str, tuple[str, str]] = {}   # referencia -> (entrada raíz, operación que la produjo)
    for name in entries:
        available[name] = (name, "entrada")
    produced: dict[str, str] = {}                # paso -> operación
    seen: set[str] = set()
    used: set[str] = set()
    for number, spec in enumerate(raw_steps, 1):
        label = f"paso {number}"
        if not isinstance(spec, dict):
            errors.append(error("parametro_invalido", "Cada paso es un objeto", label, f"pasos[{number - 1}]"))
            continue
        name = spec.get("nombre")
        if not isinstance(name, str) or not NAME.fullmatch(name):
            errors.append(error("nombre_invalido", "nombre del paso: minúsculas, dígitos y _, empezando por letra",
                                label, "nombre"))
            name = f"paso_{number}"
        elif name in seen or name in entries:
            errors.append(error("nombre_duplicado", f"El nombre {name} ya se usa en otro paso o entrada", name,
                                "nombre", "Cada paso y entrada necesita un nombre único"))
        seen.add(name)
        op = spec.get("op")
        if op not in PARAMS:
            errors.append(error("operacion_desconocida", f"Operación desconocida: {str(op)[:40]}", name, "op",
                                _near(str(op), PARAMS) or "Operaciones: " + ", ".join(PARAMS)))
            continue
        allowed, required = PARAMS[op]
        for key in sorted(set(spec) - allowed - COMMON):
            errors.append(error("parametro_desconocido", f"{op} no admite {key}", name, key,
                                _near(key, allowed | COMMON) or "Admitidos: " + ", ".join(sorted(allowed))))
        for key in sorted(required - set(spec)):
            errors.append(error("parametro_ausente", f"{op} requiere {key}", name, key))
        opciones = spec.get("opciones", {})
        if not isinstance(opciones, dict) or set(opciones) - {"decimal", "date_format"}:
            errors.append(error("parametro_invalido", "opciones admite decimal y date_format", name, "opciones"))
            opciones = {}
        mode, permitted = _policy(spec, "paso", errors, name, op in SEPARABLE)
        step = Step(number, name, op, spec, {}, incidencias=mode, permitidas=permitted)

        def ref(value, campo, step=step):
            if not isinstance(value, str) or not value:
                errors.append(error("referencia_invalida", "Una referencia es el nombre de una entrada o "
                                    "\"paso.salida\"", step.nombre, campo))
                return None
            if value in available:
                used.add(available[value][0])
                return value
            head, _, tail = value.partition(".")
            if head == step.nombre or (head not in produced and head in {s.get("nombre") for s in raw_steps
                                                                         if isinstance(s, dict)}):
                errors.append(error("referencia_adelantada", f"{value} se refiere a este paso o a uno posterior",
                                    step.nombre, campo, "Un paso solo puede usar entradas y pasos anteriores"))
            elif head in produced:
                outs = OUTPUTS[produced[head]]
                hint = ("Ese paso no produce tablas" if not outs else
                        "Use " + " o ".join(f"{head}.{o}" for o in outs))
                errors.append(error("salida_inexistente", f"{value}: el paso {head} ({produced[head]}) no tiene "
                                    f"esa salida", step.nombre, campo, hint))
            else:
                errors.append(error("referencia_inexistente", f"No existe la entrada o paso {value}", step.nombre,
                                    campo, _near(value, available)))
            return None

        if op in ("inspeccionar", "validar", "transformar", "completar", "duplicados") and "entrada" in spec:
            step.refs["entrada"] = ref(spec["entrada"], "entrada")
        if op == "comparar":
            for key in ("antes", "despues"):
                if key in spec:
                    step.refs[key] = ref(spec[key], key)
            _names(spec, "clave", name, errors)
        if op == "completar":
            if "referencia" in spec:
                step.refs["referencia"] = ref(spec["referencia"], "referencia")
            for key in ("clave", "clave_referencia", "columnas"):
                _names(spec, key, name, errors)
            if ("clave_referencia" in spec and isinstance(spec.get("clave"), list)
                    and isinstance(spec["clave_referencia"], list) and len(spec["clave"]) != len(spec["clave_referencia"])):
                errors.append(error("parametro_invalido", "clave y clave_referencia deben tener el mismo largo", name,
                                    "clave_referencia"))
            if spec.get("existentes", "error") not in EXISTENTES:
                errors.append(error("parametro_invalido", "existentes: error, completar_vacios o reemplazar", name,
                                    "existentes", "Por defecto (error) nunca se pisan datos presentes"))
        if op == "duplicados":
            for key in ("clave", "comparar"):
                _names(spec, key, name, errors)
            keep = spec.get("conservar", "ninguno")
            if keep not in CONSERVAR:
                errors.append(error("parametro_invalido", "conservar: ninguno, primero, ultimo o mas_reciente", name,
                                    "conservar", "Sin conservar (ninguno) los registros contradictorios van a conflictos"))
            if keep == "mas_reciente" and not (isinstance(spec.get("fecha"), str) and spec["fecha"]):
                errors.append(error("parametro_ausente", "mas_reciente requiere fecha (nombre de columna)", name, "fecha",
                                    "El formato se toma de date_format de la entrada u opciones"))
            if "fecha" in spec and keep != "mas_reciente":
                errors.append(error("parametro_invalido", "fecha solo se usa con conservar mas_reciente", name, "fecha"))
            if "empate" in spec and (keep != "mas_reciente" or spec["empate"] not in EMPATE):
                errors.append(error("parametro_invalido", "empate (conflicto, primero o ultimo) solo con mas_reciente",
                                    name, "empate", "Por defecto un empate de fechas es un conflicto"))
        if op == "consolidar" and "entradas" in spec:
            if not isinstance(spec["entradas"], list) or not spec["entradas"]:
                errors.append(error("parametro_invalido", "entradas: lista no vacía de referencias", name, "entradas"))
            else:
                step.refs["entradas"] = [ref(v, f"entradas[{i}]") for i, v in enumerate(spec["entradas"])]
        if op in ("consultar", "exportar") and "tablas" in spec:
            tablas = spec["tablas"]
            pattern = SQL_NAME if op == "consultar" else NAME
            if not isinstance(tablas, dict) or not tablas:
                errors.append(error("parametro_invalido", "tablas: objeto {nombre: referencia}", name, "tablas"))
            else:
                step.refs["tablas"] = {}
                for alias, value in tablas.items():
                    if not pattern.fullmatch(alias) or (op == "exportar" and alias in RESERVED):
                        errors.append(error("nombre_invalido", f"Nombre de tabla no admitido: {alias[:40]}", name,
                                            f"tablas.{alias[:40]}", "Letras, dígitos y _; en exportar, minúsculas y "
                                            "distinto de report, audit, manifiesto"))
                    step.refs["tablas"][alias] = ref(value, f"tablas.{alias[:40]}")
        if op == "consultar":
            if "sql" in spec and (not isinstance(spec["sql"], str) or not spec["sql"].strip()):
                errors.append(error("parametro_invalido", "sql: una consulta SELECT", name, "sql"))
            numeric = spec.get("numeric", [])
            if not isinstance(numeric, list) or not all(isinstance(c, str) and c for c in numeric):
                errors.append(error("parametro_invalido", "numeric: lista de columnas", name, "numeric"))
            tipos = spec.get("tipos", {})
            if not isinstance(tipos, dict) or not all(
                    isinstance(cols, dict) and cols and all(isinstance(c, str) and c and k in SQL_TYPES
                                                            for c, k in cols.items()) for cols in tipos.values()):
                errors.append(error("parametro_invalido", "tipos: {tabla: {columna: number|string}}", name, "tipos",
                                    'Ejemplo: {"t": {"horas": "number"}, "flota": {"equipo": "string"}}'))
            elif isinstance(spec.get("tablas"), dict) and set(tipos) - set(spec["tablas"]):
                errors.append(error("parametro_invalido", "tipos nombra tablas que no están en tablas: "
                                    + ", ".join(sorted(set(tipos) - set(spec["tablas"])))[:120], name, "tipos"))
            if not isinstance(spec.get("detector", True), bool):
                errors.append(error("parametro_invalido", "detector debe ser true o false", name, "detector"))
            limit = spec.get("detector_max_filas", 1)
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
                errors.append(error("parametro_invalido", "detector_max_filas: entero de 1 o más", name,
                                    "detector_max_filas"))
        if op == "transformar" and spec.get("traza", "resumida") not in TRAZA:
            errors.append(error("parametro_invalido", "traza: \"resumida\" o \"detallada\"", name, "traza"))
        if op == "inspeccionar":
            sample = spec.get("sample", 0)
            if not isinstance(sample, int) or isinstance(sample, bool) or not 0 <= sample <= SAMPLE_MAX:
                errors.append(error("parametro_invalido", "sample: entero entre 0 y 20", name, "sample"))
        if op == "exportar":
            formats = spec.get("formatos", ["csv", "json", "xlsx"])
            if not isinstance(formats, list) or not formats or set(formats) - FORMATS or len(set(formats)) != len(formats):
                errors.append(error("parametro_invalido", "formatos: lista con csv, json y/o xlsx", name, "formatos"))
            if not NAME.fullmatch(str(spec.get("archivo", name))) or spec.get("archivo") in RESERVED:
                errors.append(error("nombre_invalido", "archivo: nombre del libro xlsx (minúsculas, dígitos, _)",
                                    name, "archivo"))
            if not isinstance(spec.get("safe_csv", False), bool):
                errors.append(error("parametro_invalido", "safe_csv debe ser true o false", name, "safe_csv"))
        # Opciones del paso: las de la entrada raíz de su primera tabla, con lo que indique "opciones".
        roots = [available[r][0] for r in _flat(step.refs) if r in available]
        base_opts = entries[roots[0]].opts if roots and roots[0] in entries else Options()
        checked = _options(opciones, "opciones", errors, name)
        step.opts = replace(base_opts, decimal=checked.decimal if "decimal" in opciones else base_opts.decimal,
                            date_format=checked.date_format if "date_format" in opciones else base_opts.date_format)
        if op in ("validar", "transformar") and ("reglas" in spec or "plan" in spec):
            campo = "reglas" if op == "validar" else "plan"
            config, config_path = _config(spec[campo], base, name, campo, errors)
            if config is not None:
                try:
                    if op == "validar":
                        validate_config(config, step.opts)
                    else:
                        check_plan(config, step.opts)
                except (ValueError, TypeError, KeyError) as exc:
                    errors.append(error("configuracion_invalida", f"{campo}: {str(exc)[:160]}", name, campo,
                                        f"Manual: docs/tools/{op}.md"))
                step.config, step.config_path = config, config_path
                if config_path:
                    configs.append(config_path)
        produced[name] = op
        root_name = roots[0] if roots else ""
        for out in OUTPUTS[op]:
            available[f"{name}.{out}"] = (root_name, op)
        steps.append(step)
    for name in entries:
        if name not in used:
            errors.append(error("entrada_sin_uso", f"Ningún paso usa la entrada {name}", None, f"entradas.{name}",
                                "Quite la entrada o úsela en un paso"))
    if errors:
        raise RecipeError(errors)
    return Recipe(path, nombre.strip(), entries, steps, delimiter, configs)


def _layout(spec, where, errors, opts):
    """fila_encabezado y excluir_filas de una entrada (solo CSV/XLSX), como opciones de lectura."""
    if "fila_encabezado" not in spec and "excluir_filas" not in spec:
        return opts
    row = spec.get("fila_encabezado", 1)
    if not isinstance(row, int) or isinstance(row, bool) or row < 1:
        errors.append(error("parametro_invalido", "fila_encabezado: número de fila (1 = primera)", None,
                            f"{where}.fila_encabezado"))
        row = 1
    conditions = spec.get("excluir_filas", [])
    valid = isinstance(conditions, list) and bool(conditions) or "excluir_filas" not in spec
    for cond in conditions if isinstance(conditions, list) else []:
        tests = set(cond) - {"columna"} if isinstance(cond, dict) else set()
        if not (isinstance(cond, dict) and isinstance(cond.get("columna"), str) and len(tests) == 1
                and tests <= set(EXCLUSION_TESTS)
                and (cond.get("vacia") is True or isinstance(cond.get("igual"), str)
                     or (isinstance(cond.get("empieza_con"), str) and cond["empieza_con"]))):
            valid = False
    if not valid:
        errors.append(error("parametro_invalido", "excluir_filas: lista de condiciones {columna, y una de: igual, "
                            "empieza_con, vacia: true}", None, f"{where}.excluir_filas",
                            'Ejemplo: [{"columna": "orden", "igual": "TOTAL"}]; no se adivinan filas'))
        conditions = []
    return replace(opts, header_row=row, exclude_rows=tuple(conditions))


def _names(spec, key, step, errors):
    """Parámetro opcional que, si está, es una lista no vacía de nombres de columna distintos."""
    value = spec.get(key)
    if key in spec and not (isinstance(value, list) and value and all(isinstance(c, str) and c for c in value)
                            and len(set(value)) == len(value)):
        errors.append(error("parametro_invalido", f"{key}: lista no vacía de columnas distintas", step, key))


def _near(value, options):
    match = difflib.get_close_matches(str(value), [str(o) for o in options], n=1, cutoff=0.6)
    return f"¿Quiso decir {match[0]}?" if match else None



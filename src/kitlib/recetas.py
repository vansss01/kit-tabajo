"""Recetas: un flujo secuencial de operaciones existentes del kit, descrito en JSON.

Orden de trabajo:
1. `cargar_receta` comprueba la receta completa sin leer datos (estructura, operaciones,
   parámetros, referencias entre pasos, reglas y planes). Si algo falla no se crea nada.
2. `--vista-previa` describe lo que se haría y termina: no lee ni valida datos.
3. `ejecutar_receta` lee las entradas, ejecuta los pasos en orden y deja en la carpeta de
   la ejecución un `manifiesto.json` que se reemplaza de forma atómica tras cada paso.

No es un motor de flujos general: sin bucles, condiciones ni pasos en paralelo. La única
ramificación es elegir, por referencia, las filas aceptadas o rechazadas de un paso validar.
"""
import difflib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from kitlib import __version__, traza
from kitlib.operations import (check_plan, compare, inspect_table, merge_tables, query, query_warnings,
                               new_trace, transform, validate, validate_config)
from kitlib.runtime import ROOT, inside, public_message
from kitlib.tableio import (ORIGEN, Options, Table, atomic_json, csv_write, excel_write, fingerprint, json_write,
                            load_config, read_table, table_json)

VERSION = 1
NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")
SQL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,40}")
CODE = re.compile(r"[a-z][a-z0-9_]{0,79}")
# Tablas que produce cada operación; una referencia "paso.salida" debe nombrar una de ellas.
OUTPUTS: dict[str, tuple[str, ...]] = {
    "inspeccionar": (), "validar": ("aceptadas", "rechazadas", "incidencias"), "transformar": ("resultado",),
    "consultar": ("resultado",), "consolidar": ("resultado", "incidencias"),
    "comparar": ("nuevos", "eliminados", "cambios"), "exportar": ()}
PARAMS: dict[str, tuple[set[str], set[str]]] = {  # operación: (permitidos, obligatorios)
    "inspeccionar": ({"entrada", "sample"}, {"entrada"}),
    "validar": ({"entrada", "reglas"}, {"entrada", "reglas"}),
    "transformar": ({"entrada", "plan", "traza"}, {"entrada", "plan"}),
    "consultar": ({"tablas", "sql", "numeric"}, {"tablas", "sql"}),
    "consolidar": ({"entradas"}, {"entradas"}),
    "comparar": ({"antes", "despues", "clave"}, {"antes", "despues", "clave"}),
    "exportar": ({"tablas", "formatos", "archivo", "safe_csv"}, {"tablas"}),
}
COMMON = {"nombre", "op", "descripcion", "opciones", "politica"}
SEPARABLE = {"validar", "consolidar"}  # únicas operaciones que pueden apartar lo inválido y seguir
READ_OPTIONS = {"delimiter", "encoding", "decimal", "date_format", "sheet"}
ENTRY_KEYS = READ_OPTIONS | {"ruta", "principal", "politica", "descripcion"}
TOP_KEYS = {"version", "nombre", "descripcion", "entradas", "pasos", "salida"}
FORMATS = {"csv", "json", "xlsx"}
RESERVED = {"report", "audit", "manifiesto", "failed"}


class RecipeError(ValueError):
    """Receta inválida: lista de errores con código estable, paso, campo y sugerencia."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__(errors[0]["mensaje"] if errors else "Receta inválida")


def error(code, message, step=None, campo=None, hint=None):
    return {"codigo": code, "paso": step, "campo": campo, "mensaje": message, "sugerencia": hint}


@dataclass
class Step:
    numero: int
    nombre: str
    op: str
    spec: dict
    refs: dict[str, Any]          # campo -> referencia, lista o mapa de referencias
    opts: Options = field(default_factory=Options)
    incidencias: str = "detener"
    permitidas: set[str] = field(default_factory=set)
    config: Any = None            # reglas o plan ya cargados
    config_path: Path | None = None

    @property
    def carpeta(self):
        return f"{self.numero:02d}-{self.nombre}"


@dataclass
class Entry:
    nombre: str
    ruta: Path | None
    opts: Options
    incidencias: str = "detener"
    permitidas: set[str] = field(default_factory=set)


@dataclass
class Recipe:
    path: Path
    nombre: str
    entradas: dict[str, Entry]
    pasos: list[Step]
    delimiter: str
    configs: list[Path]


def add_parser(sub):
    cmd = sub.add_parser("ejecutar", help="Ejecutar una receta JSON de pasos del kit",
                         description="Ejecuta en orden los pasos de una receta. Sin --vista-previa crea una "
                                     "carpeta de ejecución con manifiesto.json.")
    cmd.add_argument("input", type=Path, help="Archivo de la entrada principal de la receta")
    cmd.add_argument("--receta", type=Path, required=True, help="Receta JSON (ver docs/tools/ejecutar.md)")
    cmd.add_argument("--entrada", action="append", default=[], metavar="NOMBRE=ARCHIVO",
                     help="Reemplaza el archivo de otra entrada de la receta; repetible")
    cmd.add_argument("--vista-previa", action="store_true",
                     help="Describir pasos, entradas, políticas y destinos sin leer datos ni crear resultados")
    cmd.add_argument("--output", type=Path, default=ROOT / "results", help="Carpeta de resultados dentro del proyecto")
    cmd.add_argument("--run-name", help="Nombre exclusivo de ejecución; falla si ya existe")
    cmd.add_argument("--json", action="store_true", help="Resumen compacto JSON en stdout")
    cmd.add_argument("--verbose", action="store_true", help="Añadir hasta 10 incidencias al resumen")


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
        if key == "decimal" and value not in (".", ","):
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
    if mode not in ("detener", "separar"):
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


def cargar_receta(path, principal=None, overrides=None):
    """Comprueba y resuelve una receta sin leer datos. Lanza RecipeError con todos los errores."""
    path = Path(path).resolve()
    base = path.parent
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RecipeError([error("receta_json_invalido", "La receta no es JSON UTF-8 válido: " + str(exc)[:120])]) from exc
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
        entries[name] = Entry(name, route, _options(spec, where, errors), mode, allowed)
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
        if entry.ruta is None:
            errors.append(error("entrada_sin_ruta", "La entrada no tiene archivo", None, f"entradas.{entry.nombre}",
                                f"Añada \"ruta\" o use --entrada {entry.nombre}=ARCHIVO"))
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

        if op in ("inspeccionar", "validar", "transformar") and "entrada" in spec:
            step.refs["entrada"] = ref(spec["entrada"], "entrada")
        if op == "comparar":
            for key in ("antes", "despues"):
                if key in spec:
                    step.refs[key] = ref(spec[key], key)
            if "clave" in spec and not (isinstance(spec["clave"], list) and spec["clave"]
                                        and all(isinstance(c, str) and c for c in spec["clave"])
                                        and len(set(spec["clave"])) == len(spec["clave"])):
                errors.append(error("parametro_invalido", "clave: lista no vacía de columnas distintas", name, "clave"))
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
        if op == "transformar" and spec.get("traza", "resumida") not in ("resumida", "detallada"):
            errors.append(error("parametro_invalido", "traza: \"resumida\" o \"detallada\"", name, "traza"))
        if op == "inspeccionar":
            sample = spec.get("sample", 0)
            if not isinstance(sample, int) or isinstance(sample, bool) or not 0 <= sample <= 20:
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


def _flat(refs):
    for value in refs.values():
        if isinstance(value, list):
            yield from (v for v in value if v)
        elif isinstance(value, dict):
            yield from (v for v in value.values() if v)
        elif value:
            yield value


def _near(value, options):
    match = difflib.get_close_matches(str(value), [str(o) for o in options], n=1, cutoff=0.6)
    return f"¿Quiso decir {match[0]}?" if match else None


# --------------------------------------------------------------------------- vista previa

def comprobar_columnas(recipe):
    """Lee solo el encabezado de cada entrada y ejecuta los pasos sobre tablas sin filas, con las
    mismas funciones que la ejecución real: así una columna inexistente se detecta sin procesar
    datos. Devuelve (estado por entrada, estado por paso, errores, avisos)."""
    entradas: dict[str, dict] = {}
    pasos: dict[str, dict] = {}
    errors: list[dict] = []
    notices: list[dict] = []
    known: dict[str, Table] = {}
    for name, entry in recipe.entradas.items():
        if entry.ruta.suffix.lower() == ".json":
            entradas[name] = {"encabezado": "no_comprobado",
                              "motivo": "Una tabla JSON solo puede leerse completa; se comprobará al ejecutar"}
            continue
        try:
            head = read_table(entry.ruta, entry.opts, limit=0)
        except Exception as exc:
            entradas[name] = {"encabezado": "ilegible", "motivo": public_message(exc, entry.opts.encoding)}
            notices.append(error("encabezado_ilegible", public_message(exc, entry.opts.encoding), None,
                                 f"entradas.{name}", "La ejecución fallará al leer esta entrada"))
            continue
        if head.issues or not head.columns:
            codes = ", ".join(sorted({i["codigo"] for i in head.issues})) or "sin_columnas"
            entradas[name] = {"encabezado": "invalido", "motivo": codes}
            notices.append(error("encabezado_invalido", f"Encabezado no utilizable: {codes}", None,
                                 f"entradas.{name}", "Corrija el encabezado del archivo"))
            continue
        entradas[name] = {"encabezado": "leido", "columnas": len(head.columns), "advertencias": head.warnings}
        for code in sorted(set(head.warnings) - entry.permitidas):
            notices.append(error(code, f"La entrada {name} tendrá la advertencia {code}; la política la detendrá",
                                 None, f"entradas.{name}", "Revise --delimiter o permita ese código"))
        known[name] = Table(head.columns, [], head.source)
    for step in recipe.pasos:
        missing = sorted({r for r in _flat(step.refs) if r not in known})
        if missing:
            pasos[step.nombre] = {"columnas": "no_comprobadas", "motivo": "Depende de " + ", ".join(missing)}
            continue
        try:
            outputs, issues, _, _ = RUNNERS[step.op](step, known.__getitem__)
        except Exception as exc:
            pasos[step.nombre] = {"columnas": "error", "motivo": public_message(exc)}
            errors.append(error("columnas_incompatibles", public_message(exc), step.nombre, None,
                                "Compare los nombres con el encabezado (mayúsculas, tildes y espacios cuentan)"))
            continue
        pasos[step.nombre] = {"columnas": "comprobadas"}
        if issues:
            expected = sorted({i["codigo"] for i in issues})
            stops = step.incidencias != "separar" or not outputs
            pasos[step.nombre]["incidencias_previstas"] = expected
            notices.append(error("incidencias_previstas", f"Con estos encabezados el paso dará {', '.join(expected)}"
                                 + ("; la política lo detendrá" if stops else ""), step.nombre, None,
                                 "Revise las columnas exigidas por reglas, clave o consolidación"))
        if step.op != "exportar":
            for out, table in outputs.items():
                known[f"{step.nombre}.{out}"] = Table(table.columns, [])
        if "incidencias" in OUTPUTS[step.op]:
            known[f"{step.nombre}.incidencias"] = Table(ISSUE_COLUMNS, [])
    return entradas, pasos, errors, notices


def vista_previa(recipe):
    """Descripción con encabezados: no lee filas ni garantiza que los datos cumplan nada."""
    entradas, columnas, errors, notices = comprobar_columnas(recipe)
    code = 2 if errors else 1 if notices else 0
    steps = []
    for step in recipe.pasos:
        destination = [f"{step.carpeta}/{o}.csv|json" for o in OUTPUTS[step.op]] + [f"{step.carpeta}/report.json"]
        if step.op == "exportar":
            formats = step.spec.get("formatos", ["csv", "json", "xlsx"])
            destination = [f"{step.carpeta}/{t}.{f}" for t in step.refs["tablas"] for f in formats if f != "xlsx"]
            destination += [f"{step.carpeta}/{step.spec.get('archivo', step.nombre)}.xlsx"] if "xlsx" in formats else []
        steps.append({"numero": step.numero, "nombre": step.nombre, "op": step.op, "usa": step.refs,
                      "produce": [f"{step.nombre}.{o}" for o in OUTPUTS[step.op]],
                      "politica": {"incidencias": step.incidencias,
                                   "advertencias_permitidas": sorted(step.permitidas)},
                      "destino": destination, **columnas[step.nombre]})
    unchecked = [n for n, e in entradas.items() if e["encabezado"] != "leido"]
    return {"estado": "vista_previa", "codigo_salida": code, "comando": "ejecutar", "receta": recipe.nombre,
            "datos_leidos": False, "encabezados_leidos": not unchecked,
            "aviso": "Vista previa: se comprobó la receta y, leyendo solo los encabezados, las columnas que usa "
                     "cada paso. Las filas de datos NO se leyeron ni se validaron; la ejecución puede encontrar "
                     "incidencias." + (" Encabezados no comprobados: " + ", ".join(unchecked) + "; los pasos que "
                                       "dependen de ellos no tienen columnas comprobadas." if unchecked else ""),
            "entradas": [{"nombre": e.nombre, "ruta": str(e.ruta), "delimiter": e.opts.delimiter,
                          "decimal": e.opts.decimal, "politica": {"incidencias": e.incidencias,
                          "advertencias_permitidas": sorted(e.permitidas)}, **entradas[e.nombre]}
                         for e in recipe.entradas.values()],
            "pasos": steps, "errores": errors, "avisos": notices,
            "destino": "Carpeta nueva bajo --output (se crea al ejecutar), con manifiesto.json"}


# --------------------------------------------------------------------------- ejecución

def _step_inspeccionar(step, get):
    table = get(step.refs["entrada"])
    analysis = inspect_table(table, step.opts, step.spec.get("sample", 0))
    return {}, list(analysis["incidencias"]), [], {"analisis": analysis}


def _step_validar(step, get):
    source = get(step.refs["entrada"])
    tables, issues, details = validate(source, step.config, step.opts)
    return ({"aceptadas": tables["validos"], "rechazadas": tables["invalidos"]},
            traza.remap_issues(issues, source), [], details)


def _step_transformar(step, get):
    trace = new_trace()
    tables, issues, details = transform(get(step.refs["entrada"]), step.config, step.opts, trace)
    return ({"resultado": tables["validos"]} if tables else {}), issues, [], {**details, "_traza": trace}


def _step_consultar(step, get):
    loaded = {alias: get(ref) for alias, ref in step.refs["tablas"].items()}
    tables, issues, details = query(loaded, step.spec["sql"], set(step.spec.get("numeric", [])), step.opts)
    return {"resultado": tables["validos"]}, issues, query_warnings(details, step.nombre), details


def _step_consolidar(step, get):
    output, issues, details = merge_tables([(ref, get(ref), None) for ref in step.refs["entradas"]])
    return {"resultado": output}, issues, [], details


def _step_comparar(step, get):
    tables, issues, details = compare(get(step.refs["antes"]), get(step.refs["despues"]), step.spec["clave"])
    return tables, issues, [], details


def _step_exportar(step, get):
    return {alias: get(ref) for alias, ref in step.refs["tablas"].items()}, [], [], {}


RUNNERS = {"inspeccionar": _step_inspeccionar, "validar": _step_validar, "transformar": _step_transformar,
           "consultar": _step_consultar, "consolidar": _step_consolidar, "comparar": _step_comparar,
           "exportar": _step_exportar}

ISSUE_COLUMNS = ["codigo", "fila", "columna", "origen", "detalle"]


def _codes(items):
    return dict(Counter(i["codigo"] for i in items).most_common(15))


def _now():
    return datetime.now(timezone.utc).isoformat()


def ejecutar_receta(recipe, run, args):
    """Ejecuta los pasos. Devuelve (código, resumen). El manifiesto refleja siempre el estado real."""
    manifest: dict[str, Any] = {
        "version_manifiesto": 1, "estado": "en_curso", "motivo": None, "codigo_salida": None,
        "comando": "ejecutar", "version_kit": __version__, "inicio_utc": _now(), "fin_utc": None,
        "receta": {"nombre": recipe.nombre, **fingerprint(recipe.path)},
        "configuraciones": [fingerprint(p) for p in recipe.configs],
        "entradas": {}, "pasos": [
            {"numero": s.numero, "nombre": s.nombre, "op": s.op, "carpeta": s.carpeta, "estado": "pendiente",
             "usa": s.refs, "politica": {"incidencias": s.incidencias, "advertencias_permitidas": sorted(s.permitidas)}}
            for s in recipe.pasos],
        "parametros": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        "error": None}
    path = run / "manifiesto.json"

    def save():
        atomic_json(path, manifest)

    def finish(state, code, reason=None, err=None):
        manifest.update(estado=state, codigo_salida=code, motivo=reason, error=err, fin_utc=_now())
        if state == "fallida":
            json_write(run / "FAILED.json", {"estado": "error", "motivo": reason,
                                              "nota": "Ejecución incompleta; no utilizar resultados parciales."})
        save()  # último paso: el estado final aparece de una vez, nunca antes que los archivos
        return code

    save()
    tables: dict[str, Table] = {}
    info: dict[str, dict] = {}
    issues_total: list[dict] = []
    warnings_total: list[dict] = []
    current: dict | None = None
    try:
        sources = {n: fingerprint(e.ruta) for n, e in recipe.entradas.items()}
        configs = [fingerprint(p) for p in [recipe.path, *recipe.configs]]
        # Lectura de entradas, cada una con su política.
        (run / "00-entradas").mkdir()
        read_issues: list[dict] = []
        for name, entry in recipe.entradas.items():
            table = read_table(entry.ruta, entry.opts)
            warnings = [{"origen": name, "codigo": w} for w in table.warnings]
            record = {**sources[name], "filas_leidas": table.scanned, "filas_tabulares": len(table.rows),
                      "columnas": len(table.columns), "incidencias": len(table.issues),
                      "advertencias": len(warnings), "advertencias_por_codigo": _codes(warnings),
                      "incidencias_por_codigo": _codes(table.issues)}
            manifest["entradas"][name] = record
            read_issues.extend(table.issues)
            issues_total.extend(table.issues)
            warnings_total.extend(warnings)
            refused = [w["codigo"] for w in warnings if w["codigo"] not in entry.permitidas]
            if (table.issues and entry.incidencias != "separar") or refused:
                record["estado"] = "detenida"
                _write_issues(run / "00-entradas", read_issues, recipe.delimiter)
                reason = "incidencias" if table.issues and entry.incidencias != "separar" else "advertencias"
                return finish("fallida", 2, "detenida_por_politica", {
                    "codigo": f"{reason}_no_admitidas", "paso": f"entrada {name}", "campo": "politica",
                    "mensaje": f"La entrada {name} tiene {reason} que la política no admite: "
                               + ", ".join(sorted(set(refused) or {i['codigo'] for i in table.issues}))[:200],
                    "sugerencia": "Revise 00-entradas/incidencias.csv; corrija el archivo o declare la política"})
            record["estado"] = "leida_con_incidencias" if table.issues or warnings else "leida"
            malformed = sum(i["codigo"] == "ancho_incorrecto" for i in table.issues)
            record["filas_excluidas_mal_formadas"] = malformed
            record["invariante"] = {"tipo": "particion", "regla": "filas leídas = tabulares + mal formadas "
                                    "(en 00-entradas/incidencias.csv)",
                                    "cumple": table.scanned == len(table.rows) + malformed}
            if not record["invariante"]["cumple"]:
                raise ValueError(f"Invariante incumplida al leer la entrada {name}")
            traza.tag(table, name, entry.ruta)
            # Filas mal formadas ya quedaron fuera y registradas: los pasos reciben la tabla sin repetirlas.
            tables[name] = replace(table, issues=[], warnings=[])
            info[name] = {"validada": False, "origen": f"entrada:{name}"}
        _write_issues(run / "00-entradas", read_issues, recipe.delimiter)
        save()

        for step, current in zip(recipe.pasos, manifest["pasos"], strict=True):
            current.update(estado="en_curso", inicio_utc=_now())
            save()
            folder = run / step.carpeta
            folder.mkdir()
            outputs, issues, warnings, details = RUNNERS[step.op](step, tables.__getitem__)
            trace = details.pop("_traza", None)
            issues_total.extend(issues)
            warnings_total.extend(warnings)
            refused = sorted({w["codigo"] for w in warnings} - step.permitidas)
            blocked = bool(issues) and (step.incidencias != "separar" or not outputs)
            current.update(incidencias=len(issues), advertencias=len(warnings),
                           incidencias_por_codigo=_codes(issues), advertencias_por_codigo=_codes(warnings),
                           conteos={k: v for k, v in details.items() if isinstance(v, int)})
            if issues or "incidencias" in OUTPUTS[step.op]:  # exportar puede publicar una tabla "incidencias"
                _write_issues(folder, issues, recipe.delimiter)
            json_write(folder / "report.json", {"paso": step.nombre, "op": step.op, "detalle": details,
                                                "incidencias_detalle": issues, "advertencias_detalle": warnings})
            if blocked or refused:
                # Detenido por política: queda el informe del paso, no sus tablas.
                current.update(estado="detenido", fin_utc=_now())
                kind = "incidencias" if blocked else "advertencias"
                codes = sorted({i["codigo"] for i in issues}) if blocked else refused
                hint = ("Revise " + step.carpeta + "/incidencias.csv. Si deben apartarse las filas, use "
                        "\"politica\": {\"incidencias\": \"separar\"}" if blocked and step.op in SEPARABLE else
                        "Revise " + step.carpeta + "/report.json" if blocked else
                        "Si esa advertencia es aceptable aquí, añádala a politica.advertencias_permitidas")
                return finish("fallida", 2, "detenida_por_politica", {
                    "codigo": f"{kind}_no_admitidas", "paso": step.nombre, "campo": "politica",
                    "mensaje": f"El paso {step.nombre} tiene {kind} no admitidas: " + ", ".join(codes)[:200],
                    "sugerencia": hint})
            # Invariantes antes de publicar: si una no se cumple, el paso falla sin dejar tablas.
            inputs = _inputs(step, tables)
            checks = traza.invariants(step.op, inputs, outputs, trace, details)
            current["invariantes"] = checks
            broken = [c["regla"] for c in checks if not c["cumple"]]
            if broken:
                raise ValueError(f"Invariante incumplida en el paso {step.nombre}: {broken[0]}. "
                                 "No se publicaron sus tablas")
            written = {}
            for out, table in outputs.items():
                if step.op == "exportar":
                    continue
                table_json(folder / (out + ".json"), table)
                csv_write(folder / (out + ".csv"), table, recipe.delimiter)
                ref = f"{step.nombre}.{out}"
                tables[ref] = table
                info[ref] = {"validada": step.op == "validar" and out == "aceptadas",
                             "origen": f"{step.op}:{step.nombre}",
                             "desde": sorted(set(_flat(step.refs)))}
                written[out] = {"archivo": f"{step.carpeta}/{out}.json", "filas": len(table.rows), **info[ref]}
            if step.op == "exportar":
                written = _export(step, folder, outputs, recipe.delimiter, info)
            if "incidencias" in OUTPUTS[step.op]:
                tables[f"{step.nombre}.incidencias"] = Table(ISSUE_COLUMNS, issues)
                info[f"{step.nombre}.incidencias"] = {"validada": False, "origen": f"{step.op}:{step.nombre}"}
                written["incidencias"] = {"archivo": f"{step.carpeta}/incidencias.json", "filas": len(issues),
                                          **info[f"{step.nombre}.incidencias"]}
            current.update(_trace_files(step, folder, inputs, outputs, issues, trace, details, recipe.delimiter))
            current.update(estado="completado_con_incidencias" if issues or warnings else "completado",
                           salidas=written, detalles=f"{step.carpeta}/report.json", fin_utc=_now())
            save()
        current = None
        if sources != {n: fingerprint(e.ruta) for n, e in recipe.entradas.items()} or configs != [
                fingerprint(p) for p in [recipe.path, *recipe.configs]]:
            raise ValueError("Una entrada o configuración cambió durante la ejecución; resultados descartados")
        code = 1 if issues_total or warnings_total else 0
        summary = _summary(manifest, run, issues_total, warnings_total, code,
                           "completada_con_incidencias" if code else "completada")
        audit = {"version_kit": __version__, "python": sys.version.split()[0], "fecha_utc": _now(),
                 "parametros": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                 "receta": manifest["receta"], "fuentes": list(sources.values()),
                 "configuraciones": manifest["configuraciones"], "resumen": summary,
                 "originales_sha256_sin_cambios": True}
        json_write(run / "report.json", {**summary, "incidencias_detalle": issues_total[:1000],
                                         "advertencias_detalle": warnings_total[:1000]})
        json_write(run / "audit.json", audit)
        if not run.parent.is_relative_to(ROOT / "tmp"):
            json_write(inside(ROOT / "logs" / (run.name + "-" + uuid4().hex[:8] + ".json")), audit)
        return finish(summary["estado"], code)
    except Exception as exc:
        if current is not None:
            current.update(estado="fallido", fin_utc=_now())
        return finish("fallida", 2, "error_de_ejecucion", {
            "codigo": "error_de_ejecucion", "paso": current["nombre"] if current else None, "campo": None,
            "mensaje": public_message(exc), "sugerencia": "Revise el paso indicado; los resultados no son utilizables"})
    except BaseException:
        # Interrupción (Ctrl+C): se intenta dejar constancia. Un corte abrupto deja "en_curso".
        if current is not None:
            current.update(estado="interrumpido")
        finish("fallida", 2, "interrumpida")
        raise


def _inputs(step, tables):
    """Tablas que usa el paso, con la forma que esperan los invariantes."""
    refs = step.refs
    if step.op in ("inspeccionar", "validar", "transformar"):
        return [tables[refs["entrada"]]]
    if step.op == "comparar":
        return [tables[refs["antes"]], tables[refs["despues"]]]
    if step.op == "consolidar":
        return [(ref, tables[ref]) for ref in refs["entradas"]]
    return [(alias, tables[ref]) for alias, ref in refs["tablas"].items()]  # consultar, exportar


def _trace_files(step, folder, inputs, outputs, issues, trace, details, delimiter):
    """Escribe los archivos de trazabilidad del paso y devuelve su resumen para el manifiesto."""
    files: dict[str, str] = {}
    counts: dict[str, Any] = {"entrada": sum(len((t[1] if isinstance(t, tuple) else t).rows) for t in inputs),
                              "salidas": {o: len(t.rows) for o, t in outputs.items()}}
    result: dict[str, Any] = {"filas": counts, "trazas": files}
    if step.op == "exportar":  # copia tablas ya trazadas en el paso que las produjo
        return result
    for out, table in outputs.items():
        if step.op == "comparar" and out == "cambios":
            files[out] = f"{step.carpeta}/" + traza.write_compare_changes(
                folder, inputs[0], inputs[1], step.spec["clave"], table, delimiter)
            continue
        if table.rows and all(ORIGEN not in r for r in table.rows):
            files[out] = "sin procedencia individual (" + ("agregado" if step.op == "transformar" else
                                                          "resultado SQL") + ")"
            continue
        motives = traza.motives_by_origin(issues) if (step.op, out) == ("validar", "rechazadas") else None
        name, missing = traza.write_provenance(folder, out, table, delimiter, motives)
        files[out] = f"{step.carpeta}/{name}" + (f" ({missing} filas sin procedencia individual)" if missing else "")
    if step.op == "validar" and outputs:
        counts["rechazadas"] = len(outputs["rechazadas"].rows)
    if step.op == "consolidar":
        counts["excluidas"] = sum(len(t.rows) for ref, t in inputs if ref not in details["aceptados"])
        files["excluidas"] = f"tablas rechazadas completas: {step.carpeta}/report.json (rechazados) e incidencias.csv"
    if step.op == "transformar" and trace is not None:
        counts["excluidas"] = len(trace["excluidas"])
        counts["cambios_celdas"] = len(trace["cambios"])
        files["excluidas"] = f"{step.carpeta}/" + traza.write_excluded(folder, trace, delimiter)
        files["cambios_celdas"] = f"{step.carpeta}/" + traza.write_changes(folder, trace, delimiter)
        if trace["participantes"]:
            groups = {i: s["by"] for i, s in enumerate(step.config["steps"], 1) if s["op"] == "group"}
            counts["en_grupos"] = len(trace["participantes"])
            if step.spec.get("traza") == "detallada":
                files["participantes"] = f"{step.carpeta}/" + traza.write_participants(folder, trace, groups,
                                                                                       delimiter)
            else:
                result["participacion"] = {
                    "reconstruccion": "Participan las filas de la entrada del paso que no figuran en excluidas.csv "
                                      "antes del agrupamiento; el grupo de cada una son sus valores en "
                                      + "; ".join(", ".join(b) or "(total)" for b in groups.values())
                                      + " después de los cambios de cambios_celdas.csv",
                    "detalle": "Con \"traza\": \"detallada\" se escribe participantes.csv (una línea por fila)"}
    if step.op == "consultar":
        result["participacion"] = {
            "tablas_leidas": details.get("tablas_leidas", []), "filas_candidatas": counts["entrada"],
            "nota": "SQL no se traza fila a fila: participan como candidatas todas las filas de las tablas "
                    "leídas; su procedencia está en el paso que las produjo"}
    return result


def _write_issues(folder, issues, delimiter):
    table = Table(ISSUE_COLUMNS, issues)
    table_json(folder / "incidencias.json", table)
    csv_write(folder / "incidencias.csv", table, delimiter)


def _export(step, folder, tables, delimiter, info):
    formats = step.spec.get("formatos", ["csv", "json", "xlsx"])
    written = {}
    for alias, table in tables.items():
        ref = step.refs["tablas"][alias]
        files = []
        if "json" in formats:
            table_json(folder / (alias + ".json"), table)
            files.append(alias + ".json")
        if "csv" in formats:
            csv_write(folder / (alias + ".csv"), table, delimiter, step.spec.get("safe_csv", False))
            files.append(alias + ".csv")
        written[alias] = {"archivos": [f"{step.carpeta}/{f}" for f in files], "filas": len(table.rows),
                          "desde": ref, "validada": info[ref]["validada"]}
    if "xlsx" in formats:
        name = step.spec.get("archivo", step.nombre)
        excel_write(folder / (name + ".xlsx"), tables)
        for alias in written:
            written[alias]["archivos"].append(f"{step.carpeta}/{name}.xlsx#{alias}")
    return written


def _summary(manifest, run, issues, warnings, code, state):
    return {"estado": state, "codigo_salida": code, "comando": "ejecutar", "receta": manifest["receta"]["nombre"],
            "filas_procesadas": sum(e.get("filas_leidas", 0) for e in manifest["entradas"].values()),
            "incidencias": len(issues), "advertencias": len(warnings),
            "incidencias_por_codigo": _codes(issues), "advertencias_por_codigo": _codes(warnings),
            "ruta_resultados": str(run), "manifiesto": str(run / "manifiesto.json"),
            "pasos": [{"nombre": p["nombre"], "op": p["op"], "estado": p["estado"],
                       "incidencias": p.get("incidencias", 0), "advertencias": p.get("advertencias", 0),
                       "excluidas": p.get("filas", {}).get("excluidas", 0),
                       "filas": {k: v["filas"] for k, v in p.get("salidas", {}).items()}}
                      for p in manifest["pasos"][:30]]}


# --------------------------------------------------------------------------- CLI

def _show(summary, args, issues=None):
    if args.json:
        if args.verbose and issues:
            summary["detalle_acotado"] = issues[:10]
        print(json.dumps(summary, ensure_ascii=False))
        return
    if summary["estado"] == "vista_previa":
        print("VISTA PREVIA (solo encabezados; filas no leídas ni validadas) | receta: " + summary["receta"])
        for e in summary["entradas"]:
            print(f"  entrada {e['nombre']}: {e['ruta']} (delimiter {e['delimiter']!r}, decimal {e['decimal']!r},"
                  f" incidencias={e['politica']['incidencias']}) | encabezado {e['encabezado']}"
                  + (f": {e['motivo']}" if e.get("motivo") else ""))
        for s in summary["pasos"]:
            print(f"  {s['numero']:>2} {s['nombre']} ({s['op']}) usa {json.dumps(s['usa'], ensure_ascii=False)}"
                  f" → {', '.join(s['produce']) or 'solo informe'} | incidencias={s['politica']['incidencias']}"
                  + (f", permite {', '.join(s['politica']['advertencias_permitidas'])}"
                     if s['politica']['advertencias_permitidas'] else "") + f" | columnas {s['columnas']}")
        for kind in ("errores", "avisos"):
            for err in summary[kind][:10]:
                print(f"  [{err['codigo']}] {err.get('paso') or err.get('campo')}: {err['mensaje']}")
        print(summary["destino"])
        return
    print(f"{summary['estado']} | pasos={sum(p['estado'].startswith('completado') for p in summary.get('pasos', []))}"
          f"/{len(summary.get('pasos', []))} | incidencias={summary.get('incidencias', 0)} | "
          f"advertencias={summary.get('advertencias', 0)}")
    if summary.get("ruta_resultados"):
        print("Resultados: " + summary["ruta_resultados"])
    if summary.get("error"):
        print(summary["error"])
    for p in summary.get("pasos", []):
        rows = ", ".join(f"{k}={v}" for k, v in p["filas"].items())
        print(f"  {p['nombre']} ({p['op']}): {p['estado']}" + (f" | {rows}" if rows else "")
              + (f" | incidencias={p['incidencias']}" if p["incidencias"] else "")
              + (f" | advertencias={p['advertencias']}" if p["advertencias"] else ""))
    for err in summary.get("errores", [])[:10]:
        where = " / ".join(str(x) for x in (err.get("paso"), err.get("campo")) if x)
        print(f"[{err['codigo']}] {where + ': ' if where else ''}{err['mensaje']}"
              + (f"\n    Sugerencia: {err['sugerencia']}" if err.get("sugerencia") else ""))
    for key in ("incidencias_por_codigo", "advertencias_por_codigo"):
        if summary.get(key):
            print(key + ": " + ", ".join(f"{k}={v}" for k, v in summary[key].items()))


def run(args):
    overrides = {}
    for item in args.entrada:
        name, sep, location = item.partition("=")
        if not sep or not name or not location or name in overrides:
            raise ValueError("--entrada requiere NOMBRE=ARCHIVO, sin repetir nombres")
        overrides[name] = location
    try:
        recipe = cargar_receta(args.receta, args.input, overrides)
    except RecipeError as exc:
        summary = {"estado": "error", "codigo_salida": 2, "comando": "ejecutar", "ruta_resultados": None,
                   "error": "Receta inválida: no se ejecutó nada", "errores": exc.errors[:20],
                   "total_errores": len(exc.errors)}
        _show(summary, args)
        return 2
    if args.vista_previa:
        preview = vista_previa(recipe)
        _show(preview, args)
        return preview["codigo_salida"]
    column_errors = comprobar_columnas(recipe)[2]
    if column_errors:
        _show({"estado": "error", "codigo_salida": 2, "comando": "ejecutar", "ruta_resultados": None,
               "error": "Columnas incompatibles con los encabezados: no se ejecutó nada",
               "errores": column_errors[:20], "total_errores": len(column_errors)}, args)
        return 2
    output = inside(args.output)
    run_name = args.run_name or (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-ejecutar-"
                                 + uuid4().hex[:10])
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_name) or re.fullmatch(r"(?i)con|prn|aux|nul|com\d|lpt\d", run_name):
        raise ValueError("--run-name admite letras ASCII, dígitos, guion y guion bajo (1–100), sin nombres reservados")
    output.mkdir(parents=True, exist_ok=True)
    folder = inside(output / run_name)
    folder.mkdir(exist_ok=False)
    (folder / ".kit-output").touch(exist_ok=False)
    code = ejecutar_receta(recipe, folder, args)
    manifest = json.loads((folder / "manifiesto.json").read_text(encoding="utf-8"))
    summary = {"estado": manifest["estado"], "codigo_salida": code, "comando": "ejecutar",
               "receta": recipe.nombre, "motivo": manifest["motivo"], "ruta_resultados": str(folder),
               "manifiesto": str(folder / "manifiesto.json")}
    if manifest["error"]:
        summary["errores"] = [manifest["error"]]
    issues = []
    for p in manifest["pasos"]:
        report = folder / p["carpeta"] / "report.json"
        if args.verbose and report.is_file():
            issues.extend(json.loads(report.read_text(encoding="utf-8"))["incidencias_detalle"])
    totals = _summary(manifest, folder, [], [], code, manifest["estado"])
    totals.update(incidencias=sum(p.get("incidencias", 0) for p in manifest["pasos"])
                  + sum(e.get("incidencias", 0) for e in manifest["entradas"].values()),
                  advertencias=sum(p.get("advertencias", 0) for p in manifest["pasos"])
                  + sum(e.get("advertencias", 0) for e in manifest["entradas"].values()))
    by_code: Counter = Counter()
    by_warning: Counter = Counter()
    for item in [*manifest["pasos"], *manifest["entradas"].values()]:
        by_code.update(item.get("incidencias_por_codigo", {}))
        by_warning.update(item.get("advertencias_por_codigo", {}))
    totals.update(incidencias_por_codigo=dict(by_code.most_common(15)),
                  advertencias_por_codigo=dict(by_warning.most_common(15)))
    _show({**totals, **summary}, args, issues)
    return code

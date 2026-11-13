"""Contrato para agentes: `catalogo` (capacidades del kit en JSON, generado desde el código) y
`comprobar` (revisa una receta, plan o reglas sin ejecutar nada ni leer datos)."""
import json
from pathlib import Path

from kitlib import __version__, codigos
from kitlib.esquemas import REGLAS_SEMANTICAS, SCHEMA_VERSION
from kitlib.operations import (AGGREGATES, CASES, FILTER_OPERATORS, SCHEMAS, TYPES, UNKNOWN_VALUES, check_step,
                               validate_config)
from kitlib.receta_modelo import (CONSERVAR, EMPATE, EXISTENTES, INCIDENCIAS, OUTPUTS, PARAMS, SEPARABLE, TRAZA,
                                  VERSION, RecipeError, error)
from kitlib.receta_validacion import cargar_receta
from kitlib.runtime import public_message
from kitlib.tableio import Options, unique_keys

TIPOS = ("receta", "plan", "reglas")
ALCANCE = ("Solo configuración: se comprobó estructura, parámetros y referencias. No se leyeron datos ni "
           "encabezados (columnas: ejecutar --vista-previa; datos: validar o ejecutar).")


def add_parsers(sub):
    cmd = sub.add_parser("catalogo", help="Capacidades del kit en JSON (para agentes)",
                         description="Comandos, operaciones, políticas, códigos y versiones, generados desde el código.")
    cmd.set_defaults(json=True, verbose=False)
    cmd = sub.add_parser("comprobar", help="Comprobar una receta, plan o reglas sin ejecutar nada",
                         description="Revisa solo la configuración: no lee datos ni encabezados ni crea resultados.")
    cmd.add_argument("archivo", type=Path, help="Receta, plan o reglas (JSON)")
    cmd.add_argument("--tipo", choices=TIPOS, help="Tipo de archivo; si se omite se deduce del contenido")
    cmd.add_argument("--principal", type=Path, help="Receta: archivo de la entrada principal (opcional)")
    cmd.add_argument("--json", action="store_true", help="Resultado estructurado en JSON")
    cmd.set_defaults(verbose=False)


def _arguments(subparser):
    found = []
    for action in subparser._actions:
        if action.dest == "help":
            continue
        found.append({"nombre": action.option_strings[0] if action.option_strings else action.dest,
                      "obligatorio": bool(action.required), "ayuda": action.help,
                      **({"opciones": list(action.choices)} if action.choices else {})})
    return found


def catalogo(build_parser):
    """Todo se lee de las tablas que usa el kit: nada de esta función es una lista escrita aparte."""
    parser = build_parser()
    commands = next(a for a in parser._actions if a.dest == "command")
    helps = {c.dest: c.help for c in commands._choices_actions}
    return {
        "version_kit": __version__, "version_receta": VERSION,
        "esquemas": {name: {"archivo": f"schemas/{name}.schema.json", "version": SCHEMA_VERSION} for name in TIPOS},
        "reglas_semanticas": {k: {"regla": v[0], "donde": v[1], "codigos": v[2]} for k, v in REGLAS_SEMANTICAS.items()},
        "comandos": {name: {"ayuda": helps.get(name), "argumentos": _arguments(sub)}
                     for name, sub in commands.choices.items()},
        "operaciones_receta": {op: {"parametros": sorted(allowed), "obligatorios": sorted(required),
                                    "salidas": list(OUTPUTS[op]), "puede_separar": op in SEPARABLE}
                               for op, (allowed, required) in PARAMS.items()},
        "operaciones_plan": {op: {"parametros": sorted(allowed - {"op"}), "obligatorios": sorted(required)}
                             for op, (allowed, required) in SCHEMAS.items()},
        "valores": {"tipos": sorted(TYPES), "operadores_filtro": list(FILTER_OPERATORS), "agregados": list(AGGREGATES),
                    "normalize_case": list(CASES), "replace_unknown": list(UNKNOWN_VALUES), "traza": list(TRAZA),
                    "completar_existentes": list(EXISTENTES), "duplicados_conservar": list(CONSERVAR),
                    "duplicados_empate": list(EMPATE)},
        "politicas": {"incidencias": list(INCIDENCIAS), "por_defecto": "detener",
                      "separar_en": sorted(SEPARABLE) + ["entradas"],
                      "advertencias_permitidas": "lista de códigos exactos; sin comodines"},
        "codigos_salida": {str(k): v for k, v in codigos.CODIGOS_SALIDA.items()},
        "estados_ejecucion": codigos.ESTADOS_EJECUCION, "motivos_fallo": list(codigos.MOTIVOS_FALLO),
        "estados_paso": codigos.ESTADOS_PASO,
        "codigos": {"errores": codigos.ERRORES, "incidencias": codigos.INCIDENCIAS,
                    "advertencias": codigos.ADVERTENCIAS},
    }


def _detect(config):
    if isinstance(config, dict):
        if "pasos" in config or "version" in config or "entradas" in config:
            return "receta"
        if "steps" in config:
            return "plan"
        if "columns" in config:
            return "reglas"
    return None


def _check_plan(config):
    if not isinstance(config, dict) or set(config) != {"steps"} or not isinstance(config["steps"], list):
        return [error("configuracion_invalida", "Plan: objeto con steps (lista de operaciones)", None, "steps")]
    found = []
    for number, step in enumerate(config["steps"], 1):
        try:
            check_step(step, Options())
        except ValueError as exc:
            found.append(error("configuracion_invalida", str(exc)[:200], f"plan paso {number}", f"steps[{number - 1}]",
                               "Manual: docs/tools/transformar.md"))
    return found


def comprobar(path, tipo=None, principal=None):
    """Devuelve (tipo, errores, resumen) sin leer datos ni crear nada."""
    path = Path(path)
    try:
        config = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    except FileNotFoundError:
        return tipo, [error("archivo_no_encontrado", "No existe el archivo", None, None, "Revise la ruta")], {}
    except (UnicodeError, json.JSONDecodeError) as exc:
        return tipo, [error("json_invalido", "No es JSON UTF-8 válido: " + str(exc)[:120])], {}
    except ValueError as exc:  # unique_keys
        return tipo, [error("clave_json_repetida", str(exc)[:160], None, None,
                            "Cada nombre puede aparecer una sola vez en un mismo objeto")], {}
    tipo = tipo or _detect(config)
    if tipo is None:
        return None, [error("tipo_desconocido", "No parece receta (pasos), plan (steps) ni reglas (columns)", None,
                            None, "Indique --tipo receta, plan o reglas")], {}
    if tipo == "plan":
        found = _check_plan(config)
        return tipo, found, {"pasos": [s.get("op") for s in config.get("steps", []) if isinstance(s, dict)]
                             if isinstance(config, dict) and isinstance(config.get("steps"), list) else []}
    if tipo == "reglas":
        try:
            if not isinstance(config, dict):
                raise ValueError("Las reglas deben ser un objeto JSON")
            validate_config(config, Options())
        except ValueError as exc:
            return tipo, [error("configuracion_invalida", str(exc)[:200], None, None, "Manual: docs/tools/validar.md")], {}
        return tipo, [], {"columnas": len(config["columns"]), "unique_keys": len(config.get("unique_keys", []))}
    try:
        recipe = cargar_receta(path, principal, principal_opcional=principal is None)
    except RecipeError as exc:
        return tipo, exc.errors, {}
    return tipo, [], {"nombre": recipe.nombre, "entradas": sorted(recipe.entradas),
                      "pasos": [f"{s.nombre} ({s.op})" for s in recipe.pasos]}


def run(args, build_parser):
    if args.command == "catalogo":
        print(json.dumps(catalogo(build_parser), ensure_ascii=False, indent=1))
        return 0
    try:
        tipo, found, summary = comprobar(args.archivo, args.tipo, args.principal)
    except Exception as exc:  # cualquier fallo inesperado: estructurado, sin traceback
        tipo, found, summary = args.tipo, [error("configuracion_invalida", public_message(exc))], {}
    code = 2 if found else 0
    result = {"estado": "invalida" if found else "valida", "codigo_salida": code, "comando": "comprobar",
              "tipo": tipo, "archivo": str(args.archivo), "version_esquema": SCHEMA_VERSION, "alcance": ALCANCE,
              "errores": found[:50], "total_errores": len(found), "resumen": summary}
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return code
    print(f"{result['estado']} | {tipo or 'tipo desconocido'} | errores={len(found)}")
    print(ALCANCE)
    for err in found[:20]:
        where = " / ".join(str(x) for x in (err.get("paso"), err.get("campo")) if x)
        print(f"[{err['codigo']}] {where + ': ' if where else ''}{err['mensaje']}"
              + (f"\n    Sugerencia: {err['sugerencia']}" if err.get("sugerencia") else ""))
    return code

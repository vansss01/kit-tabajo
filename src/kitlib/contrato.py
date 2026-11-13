"""Contrato para agentes: `catalogo` (capacidades del kit en JSON, generado desde el código) y
`comprobar` (revisa una receta, plan o reglas sin ejecutar nada ni leer datos)."""
import difflib
import json
from pathlib import Path

from kitlib import __version__, codigos
from kitlib.esquemas import REGLAS_SEMANTICAS, SCHEMA_VERSION
from kitlib.operations import (AGGREGATES, CASES, FILTER_OPERATORS, SCHEMAS, TYPES, UNKNOWN_VALUES, check_step,
                               validate_config)
from kitlib.receta_modelo import (CONSERVAR, EMPATE, EXISTENTES, INCIDENCIAS, OUTPUTS, PARAMS, SEPARABLE, TRAZA,
                                  VERSION, RecipeError, error)
from kitlib.receta_validacion import cargar_receta
from kitlib.runtime import ROOT, KitError, inside, public_message
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


MAX_N = 100  # tope de incidencias por consulta, aunque se pida más


def add_results_parser(sub):
    cmd = sub.add_parser("resultados", help="Leer el resumen, un paso o incidencias de una ejecución",
                         description="Lee los archivos de una ejecución sin abrir carpetas; nunca muestra valores de celdas.")
    cmd.add_argument("ejecucion", nargs="?", help="Nombre o ruta de la ejecución; por defecto la más reciente")
    cmd.add_argument("--paso", help="Detalle de un paso (solo ejecuciones de recetas)")
    cmd.add_argument("--incidencias", metavar="CODIGO", help="Primeras N incidencias o advertencias con ese código")
    cmd.add_argument("--n", type=int, default=10, help=f"Cuántas mostrar con --incidencias (10; máximo {MAX_N})")
    cmd.add_argument("--output", type=Path, default=ROOT / "results", help="Carpeta donde están las ejecuciones")
    cmd.add_argument("--json", action="store_true", help="Resultado estructurado en JSON")
    cmd.set_defaults(verbose=False)


def _run_folder(args):
    base = inside(args.output)
    if args.ejecucion:
        candidate = Path(args.ejecucion)
        folder = candidate if candidate.is_dir() else base / args.ejecucion
    else:
        runs = [p for p in base.iterdir() if (p / ".kit-output").is_file()] if base.is_dir() else []
        folder = max(runs, key=lambda p: (p.stat().st_mtime, p.name)) if runs else base / "(ninguna)"
    folder = inside(folder)
    if not (folder / ".kit-output").is_file():
        raise KitError("No se encontró esa ejecución", "ejecucion", "Use el nombre que mostró el comando o "
                       "./kit resultados sin argumentos para la más reciente", codigo="ejecucion_no_encontrada")
    return folder


def _load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _summary(folder):
    report, manifest = _load(folder / "report.json"), _load(folder / "manifiesto.json")
    base = manifest or report or {}
    result = {"ejecucion": folder.name, "ruta": str(folder), "tipo": "receta" if manifest else "comando",
              "estado": base.get("estado", "fallida" if (folder / "FAILED.json").exists() else "desconocido"),
              "codigo_salida": base.get("codigo_salida"), "completa": report is not None,
              "fallida": (folder / "FAILED.json").exists()}
    if report:
        result.update({k: report.get(k) for k in ("comando", "filas_procesadas", "incidencias", "advertencias")})
        for key in ("incidencias_detalle", "advertencias_detalle"):
            counts: dict = {}
            for item in report.get(key) or []:
                counts[item["codigo"]] = counts.get(item["codigo"], 0) + 1
            result[key.replace("_detalle", "_por_codigo")] = dict(sorted(counts.items(), key=lambda kv: -kv[1])[:15])
    if manifest:
        result.update(motivo=manifest.get("motivo"), error=manifest.get("error"), pasos=[
            {"nombre": p["nombre"], "op": p["op"], "estado": p["estado"], "incidencias": p.get("incidencias", 0),
             "advertencias": p.get("advertencias", 0), "filas": p.get("filas", {}).get("salidas", {})}
            for p in manifest["pasos"][:30]])
    if result["estado"] == "en_curso" or not result["completa"]:
        result["aviso"] = "Ejecución incompleta o en curso: no usar sus resultados"
    result["archivos"] = sorted(p.name for p in folder.iterdir() if not p.name.startswith("."))[:40]
    return result


def _step(folder, name):
    manifest = _load(folder / "manifiesto.json")
    if not manifest:
        raise KitError("Solo las ejecuciones de recetas tienen pasos", "--paso")
    steps = {p["nombre"]: p for p in manifest["pasos"]}
    if name not in steps:
        raise KitError(f"No hay un paso {name[:40]}", "--paso", "Pasos: " + ", ".join(list(steps)[:20]))
    step = steps[name]
    keys = ("numero", "nombre", "op", "estado", "carpeta", "usa", "politica", "filas", "conteos", "invariantes",
            "trazas", "participacion", "salidas", "incidencias", "advertencias", "incidencias_por_codigo",
            "advertencias_por_codigo", "detalles", "inicio_utc", "fin_utc")
    detail = {k: step[k] for k in keys if k in step}
    if manifest.get("error") and manifest["error"].get("paso") == name:
        detail["error"] = manifest["error"]
    return detail


def _issues(folder, code):
    """Incidencias y advertencias con ese código, de la ejecución o de cada paso de una receta (sin las
    copias que un paso exportar pueda haber publicado con el nombre incidencias)."""
    manifest = _load(folder / "manifiesto.json") or {"pasos": []}
    exported = {p["carpeta"] for p in manifest["pasos"] if p["op"] == "exportar"}
    sources = [("", folder)] + [(p.name, p) for p in sorted(folder.iterdir()) if p.is_dir() and p.name not in exported]
    found = []
    for step, place in sources:
        table = _load(place / "incidencias.json")
        for row in (table or {}).get("rows", []):
            if row.get("codigo") == code:
                found.append({"tipo": "incidencia", "paso": step or None, **row})
        report = _load(place / "report.json") or {}
        for item in report.get("advertencias_detalle") or []:
            if item.get("codigo") == code:
                found.append({"tipo": "advertencia", "paso": step or None, **item})
    return found


def results(args):
    if args.n < 1:
        raise KitError("--n debe ser 1 o más", "--n")
    folder = _run_folder(args)
    if args.paso:
        return {"comando": "resultados", "ejecucion": folder.name, "paso": _step(folder, args.paso)}
    if args.incidencias:
        if args.incidencias not in codigos.INCIDENCIAS | codigos.ADVERTENCIAS:
            known = sorted(codigos.INCIDENCIAS | codigos.ADVERTENCIAS)
            near = difflib.get_close_matches(args.incidencias, known, n=3, cutoff=0.6)
            raise KitError("Código de incidencia o advertencia desconocido", "--incidencias",
                           "Códigos: docs/CODIGOS.md" + (". ¿Quiso decir " + ", ".join(near) + "?" if near else ""))
        found = _issues(folder, args.incidencias)
        limit = min(args.n, MAX_N)
        return {"comando": "resultados", "ejecucion": folder.name, "codigo": args.incidencias, "total": len(found),
                "mostradas": min(limit, len(found)), "limite": limit, "maximo": MAX_N,
                "elementos": [{k: (str(v)[:200] if isinstance(v, str) else v) for k, v in item.items()}
                              for item in found[:limit]]}
    return {"comando": "resultados", **_summary(folder)}


def _print_results(result):
    if "paso" in result:
        step = result["paso"]
        print(f"{step['nombre']} ({step['op']}): {step['estado']} | filas={json.dumps(step.get('filas', {}))}")
        for check in step.get("invariantes", []):
            print(f"  invariante {check['tipo']}: {'cumple' if check['cumple'] else 'NO CUMPLE'} — {check['regla']}")
        for name, where in step.get("trazas", {}).items():
            print(f"  traza {name}: {where}")
        if step.get("error"):
            print(f"  [{step['error']['codigo']}] {step['error']['mensaje']}")
        return
    if "codigo" in result:
        print(f"{result['codigo']}: {result['mostradas']} de {result['total']} (límite {result['limite']})")
        for item in result["elementos"]:
            print("  " + " | ".join(f"{k}={item[k]}" for k in ("tipo", "paso", "fila", "columna", "detalle")
                                    if item.get(k) is not None))
        return
    print(f"{result['ejecucion']}: {result['estado']} | {result['tipo']} | código {result['codigo_salida']}")
    if result.get("aviso"):
        print("AVISO: " + result["aviso"])
    for key in ("incidencias_por_codigo", "advertencias_por_codigo"):
        if result.get(key):
            print(key + ": " + ", ".join(f"{k}={v}" for k, v in result[key].items()))
    for step in result.get("pasos", []):
        print(f"  {step['nombre']} ({step['op']}): {step['estado']}")


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
    if args.command == "resultados":
        result = results(args)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            _print_results(result)
        return 0
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

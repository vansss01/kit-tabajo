"""Vista previa de una receta: encabezados y columnas comprobados sin leer filas de datos."""

from kitlib.runtime import public_message
from kitlib.tableio import (Table, read_table)
from kitlib.receta_modelo import (OUTPUTS, error, _flat)
from kitlib.recetas import ISSUE_COLUMNS, RUNNERS


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
            errors.append(error("encabezado_ilegible", public_message(exc, entry.opts.encoding), None,
                                f"entradas.{name}", "La ejecución fallaría al leer esta entrada"))
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



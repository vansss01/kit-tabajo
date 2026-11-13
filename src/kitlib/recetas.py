"""Recetas: ejecución de los pasos (un flujo secuencial de operaciones existentes del kit).

Módulos de las recetas:
- receta_modelo: definiciones (operaciones, parámetros, salidas, políticas) y errores.
- receta_validacion: `cargar_receta` comprueba la receta completa sin leer datos.
- receta_vista: `--vista-previa` y comprobación de columnas con solo los encabezados.
- recetas (este): `ejecutar_receta` lee las entradas, ejecuta los pasos, aplica las políticas,
  escribe la traza y deja un `manifiesto.json` que se reemplaza de forma atómica tras cada paso.
- receta_cli: el comando `ejecutar`.

No es un motor de flujos general: sin bucles, condiciones ni pasos en paralelo. La única
ramificación es elegir, por referencia, salidas separadas (aceptadas/rechazadas, etc.).
"""
import sys
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from kitlib import __version__, traza
from kitlib.operations import (compare, inspect_table, merge_tables, query, query_warnings,
                               enrich, new_trace, split_duplicates, transform, validate)
from kitlib.runtime import ROOT, inside, public_message
from kitlib.tableio import (ORIGEN, Table, atomic_json, csv_write, excel_write, fingerprint, json_write,
                            read_table, table_json)
from kitlib.receta_modelo import OUTPUTS, SEPARABLE, SEPARATED, _flat


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
    warnings = details.pop("advertencias", [])
    return ({"resultado": tables["validos"]} if tables else {}), issues, warnings, {**details, "_traza": trace}


def _step_consultar(step, get):
    loaded = {alias: get(ref) for alias, ref in step.refs["tablas"].items()}
    trace: dict = {}
    tables, issues, details = query(loaded, step.spec["sql"], set(step.spec.get("numeric", [])), step.opts, trace)
    return {"resultado": tables["validos"]}, issues, query_warnings(details, step.nombre), {**details, "_traza": trace}


def _step_consolidar(step, get):
    output, issues, details = merge_tables([(ref, get(ref), None) for ref in step.refs["entradas"]])
    return {"resultado": output}, issues, [], details


def _step_comparar(step, get):
    tables, issues, details = compare(get(step.refs["antes"]), get(step.refs["despues"]), step.spec["clave"])
    return tables, issues, [], details


def _step_exportar(step, get):
    return {alias: get(ref) for alias, ref in step.refs["tablas"].items()}, [], [], {}


def _step_completar(step, get):
    source, reference = get(step.refs["entrada"]), get(step.refs["referencia"])
    keys = step.spec["clave"]
    tables, issues, ref_issues, changes, details = enrich(
        source, reference, keys, step.spec.get("clave_referencia", keys), step.spec["columnas"],
        step.spec.get("existentes", "error"))
    issues = traza.remap_issues(ref_issues, reference) + traza.remap_issues(issues, source)
    return tables, issues, [], {**details, "_traza": {"cambios": changes}}


def _step_duplicados(step, get):
    source = get(step.refs["entrada"])
    spec = step.spec
    tables, issues, motives, details = split_duplicates(
        source, spec["clave"], spec.get("conservar", "ninguno"), spec.get("fecha"), spec.get("empate", "conflicto"),
        spec.get("comparar"), step.opts)
    return tables, traza.remap_issues(issues, source), [], {**details, "_traza": {"motivos": motives}}


RUNNERS = {"inspeccionar": _step_inspeccionar, "validar": _step_validar, "transformar": _step_transformar,
           "consultar": _step_consultar, "consolidar": _step_consolidar, "comparar": _step_comparar,
           "exportar": _step_exportar, "completar": _step_completar, "duplicados": _step_duplicados}

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
        excluded: list[tuple] = []
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
            record["filas_excluidas_por_condicion"] = len(table.excluded)
            record["fila_encabezado"] = entry.opts.header_row
            excluded.extend((name, entry.ruta, table.columns, item) for item in table.excluded)
            record["invariante"] = {"tipo": "particion", "regla": "filas leídas = tabulares + mal formadas "
                                    "(00-entradas/incidencias.csv) + excluidas por condición (00-entradas/excluidas.csv)",
                                    "cumple": table.scanned == len(table.rows) + malformed + len(table.excluded)}
            if not record["invariante"]["cumple"]:
                raise ValueError(f"Invariante incumplida al leer la entrada {name}")
            traza.tag(table, name, entry.ruta)
            # Filas mal formadas ya quedaron fuera y registradas: los pasos reciben la tabla sin repetirlas.
            tables[name] = replace(table, issues=[], warnings=[])
            info[name] = {"validada": False, "origen": f"entrada:{name}"}
        _write_issues(run / "00-entradas", read_issues, recipe.delimiter)
        if any(e.opts.exclude_rows for e in recipe.entradas.values()):
            traza.write_entry_exclusions(run / "00-entradas", excluded, recipe.delimiter)
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
    if step.op in ("inspeccionar", "validar", "transformar", "duplicados"):
        return [tables[refs["entrada"]]]
    if step.op == "completar":
        return [tables[refs["entrada"]], tables[refs["referencia"]]]
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
        motives = None
        if out in SEPARATED and step.op != "transformar":
            motives = (trace or {}).get("motivos") or traza.motives_by_origin(issues)
        name, missing = traza.write_provenance(folder, out, table, delimiter, motives)
        files[out] = f"{step.carpeta}/{name}" + (f" ({missing} filas sin procedencia individual)" if missing else "")
    if step.op == "validar" and outputs:
        counts["rechazadas"] = len(outputs["rechazadas"].rows)
    if step.op == "completar" and outputs:
        counts["apartadas"] = sum(len(outputs[o].rows) for o in ("sin_coincidencia", "ambiguas", "clave_vacia"))
    if step.op == "duplicados" and outputs:
        counts["excluidas"] = len(outputs["excluidas"].rows)
        counts["conflictos"] = len(outputs["conflictos"].rows)
    if trace is not None and "cambios" in trace and step.op != "transformar":
        counts["cambios_celdas"] = len(trace["cambios"])
        files["cambios_celdas"] = f"{step.carpeta}/" + traza.write_changes(folder, trace, delimiter)
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
            "tablas_leidas": (trace or {}).get("tablas_leidas", []), "filas_candidatas": counts["entrada"],
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

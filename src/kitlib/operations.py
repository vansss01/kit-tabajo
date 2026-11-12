"""Operaciones declarativas; no eval, exec, SQL ni expresiones de Python."""
import json
import math
import re
import sqlite3
from collections import Counter
from dataclasses import replace
from decimal import Decimal, localcontext
from typing import Any

from kitlib.tableio import ORIGEN, Table, convert, empty, infer, issue, literal, number, public_row, real_text

TYPES = {"string", "integer", "number", "date", "boolean"}


def require_columns(table, columns):
    if not isinstance(columns, list) or not columns or not all(isinstance(c, str) for c in columns):
        raise ValueError("Se esperaba una lista no vacía de columnas")
    if len(set(columns)) != len(columns):
        raise ValueError("Lista de columnas duplicadas")
    missing = sorted(set(columns) - set(table.columns))
    if missing:
        raise ValueError("Columnas inexistentes: " + ", ".join(missing))


def copy_table(table, rows, columns=None):
    return Table(list(table.columns if columns is None else columns), rows, table.source, table.sheet,
                 scanned=len(rows), row_numbers=list(range(2, len(rows) + 2)))


def inspect_table(table, opts, sample):
    stats = {}
    for col in table.columns:
        values = [r[col] for r in table.rows]
        kinds: Counter = Counter()
        for value, count in Counter(values).items():  # inferir una vez por valor distinto
            kinds[infer(value, opts)] += count
        stats[col] = {"tipos_inferidos": dict(kinds), "nulos_o_vacios": sum(empty(v) for v in values)}
    keys = [tuple(r[c] for c in table.columns) for r in table.rows]
    return {"origen": table.source, "hoja": table.sheet,
            "alcance": ("estructura_no_analizable" if any(i["codigo"] == "encabezado_vacio_o_duplicado" for i in table.issues)
                        else "completo" if table.complete else "muestra_inicial"),
            "filas_totales": table.scanned if table.complete else None,
            "filas_analizadas": table.scanned, "filas_estructuralmente_validas": len(table.rows),
            "duplicados_adicionales_en_alcance": len(keys) - len(set(keys)),
            "columnas": stats, "muestra": [public_row(r) for r in table.rows[:sample]],
            "advertencias": table.warnings, "incidencias": table.issues}


def key_issues(table, keys):
    require_columns(table, keys)
    found: dict[tuple, int] = {}
    issues = []
    for idx, row in enumerate(table.rows):
        key = tuple(row[c] for c in keys)
        rowno = table.row_numbers[idx] if table.row_numbers else idx + 2
        if any(empty(v) for v in key):
            issues.append(issue("clave_vacia", rowno, ",".join(keys), table.source))
        elif key in found:
            issues.append(issue("clave_duplicada", rowno, ",".join(keys), table.source,
                                f"primera_fila={found[key]}"))
        else:
            found[key] = rowno
    return issues


def compare(before, after, keys):
    issues = before.issues + after.issues + key_issues(before, keys) + key_issues(after, keys)
    if set(before.columns) != set(after.columns):
        issues.append(issue("columnas_incompatibles", detail=json.dumps({
            "solo_antes": sorted(set(before.columns) - set(after.columns)),
            "solo_despues": sorted(set(after.columns) - set(before.columns))}, ensure_ascii=False)))
    if issues:
        return {}, issues, {"comparacion_bloqueada": True}
    left = {tuple(r[c] for c in keys): r for r in before.rows}
    right = {tuple(r[c] for c in keys): r for r in after.rows}
    new = [r for k, r in right.items() if k not in left]
    removed = [r for k, r in left.items() if k not in right]
    changes = []
    modified = unchanged = 0
    for key in left.keys() & right.keys():
        fields = [c for c in before.columns if c not in keys and left[key][c] != right[key][c]]
        modified += bool(fields)
        unchanged += not fields
        label = json.dumps(dict(zip(keys, key, strict=True)), ensure_ascii=False) if fields else ""
        for col in fields:
            changes.append({"clave": label, "campo": col, "antes": left[key][col], "despues": right[key][col]})
    changes.sort(key=lambda r: (r["clave"], r["campo"]))
    return {"nuevos": copy_table(after, new), "eliminados": copy_table(before, removed),
            "cambios": Table(["clave", "campo", "antes", "despues"], changes)}, [], {
                "nuevos": len(new), "eliminados": len(removed), "modificados": modified,
                "sin_cambios": unchanged, "campos_cambiados": len(changes)}


def validate_config(config, defaults):
    if set(config) - {"columns", "unique_keys"} or not isinstance(config.get("columns"), dict):
        raise ValueError("Reglas: columns (objeto) y unique_keys (lista opcional)")
    allowed = {"required", "nonempty", "unique", "type", "min", "max", "date_format", "decimal", "allowed"}
    for col, spec in config["columns"].items():
        if not isinstance(spec, dict) or set(spec) - allowed:
            raise ValueError(f"Regla inválida en {col}")
        if spec.get("type", "string") not in TYPES:
            raise ValueError(f"Tipo desconocido en {col}")
        for flag in ("required", "nonempty", "unique"):
            if flag in spec and not isinstance(spec[flag], bool):
                raise ValueError(f"{flag} debe ser booleano")
        if "allowed" in spec and (not isinstance(spec["allowed"], list) or not spec["allowed"]
                                  or not all(isinstance(v, str) for v in spec["allowed"])):
            raise ValueError("allowed debe ser una lista no vacía de textos")
        if spec.get("decimal", ".") not in (".", ","):
            raise ValueError("decimal debe ser . o ,")
        if "date_format" in spec and not isinstance(spec["date_format"], str):
            raise ValueError("date_format debe ser texto")
        if ("min" in spec or "max" in spec) and spec.get("type") not in {"number", "integer", "date"}:
            raise ValueError("Rangos requieren tipo number, integer o date")
        bounds = {}
        for bound in ("min", "max"):
            if bound in spec:
                rule_opts = replace(defaults, decimal=spec.get("decimal", defaults.decimal),
                                    date_format=spec.get("date_format", defaults.date_format))
                if empty(spec[bound]):
                    raise ValueError("Los límites de rango no pueden estar vacíos")
                parsed_bound = convert(spec[bound], spec["type"], rule_opts)
                bounds[bound] = Decimal(parsed_bound) if spec["type"] in {"number", "integer"} else parsed_bound
        if "min" in bounds and "max" in bounds and bounds["min"] > bounds["max"]:
            raise ValueError("El mínimo no puede exceder el máximo")
    for keys in config.get("unique_keys", []):
        if not isinstance(keys, list) or not keys or not all(isinstance(c, str) for c in keys):
            raise ValueError("unique_keys requiere listas de columnas")
    if not isinstance(config.get("unique_keys", []), list):
        raise ValueError("unique_keys debe ser lista")


def validate(table, config, opts):
    validate_config(config, opts)
    issues = list(table.issues)
    bad_rows = set()
    missing = []
    for col, spec in config["columns"].items():
        if col not in table.columns:
            if spec.get("required", False):
                missing.append(col)
                issues.append(issue("columna_obligatoria_ausente", column=col, source=table.source))
            continue
        counts = Counter(r[col] for r in table.rows if not empty(r[col]))
        rule_opts = replace(opts, decimal=spec.get("decimal", opts.decimal),
                            date_format=spec.get("date_format", opts.date_format))
        permitted = set(spec["allowed"]) if "allowed" in spec else None
        kind = spec.get("type")
        limits = {b: typed(spec[b], kind, rule_opts) for b in ("min", "max") if b in spec}
        checked: dict[Any, tuple[str, ...]] = {}  # resultado por valor distinto: los valores se repiten

        def type_codes(value):
            try:
                current = typed(value, kind, rule_opts)
            except (ValueError, TypeError):
                return ("tipo_o_fecha_invalido",)
            found = []
            if "min" in limits and current < limits["min"]:
                found.append("fuera_de_rango_min")
            if "max" in limits and current > limits["max"]:
                found.append("fuera_de_rango_max")
            return tuple(found)

        for idx, row in enumerate(table.rows):
            rowno = table.row_numbers[idx] if table.row_numbers else idx + 2
            value = row[col]
            codes = []
            if empty(value):
                if spec.get("nonempty"):
                    codes.append("campo_vacio")
            else:
                if spec.get("unique") and counts[value] > 1:
                    codes.append("valor_no_unico")
                if permitted is not None and value not in permitted:
                    codes.append("valor_no_permitido")
                if kind is not None:
                    if value not in checked:
                        checked[value] = type_codes(value)
                    codes.extend(checked[value])
            for code in codes:
                bad_rows.add(idx)
                issues.append(issue(code, rowno, col, table.source))
    for keys in config.get("unique_keys", []):
        absent = set(keys) - set(table.columns)
        if absent:
            missing.extend(absent)
            issues.append(issue("columnas_clave_ausentes", column=",".join(sorted(absent)), source=table.source))
            continue
        counts = Counter(tuple(r[c] for c in keys) for r in table.rows)
        for idx, row in enumerate(table.rows):
            key = tuple(row[c] for c in keys)
            key_code = "clave_vacia" if any(empty(v) for v in key) else "clave_duplicada" if counts[key] > 1 else None
            if key_code:
                bad_rows.add(idx)
                issues.append(issue(key_code, table.row_numbers[idx] if table.row_numbers else idx + 2,
                                    ",".join(keys), table.source))
    if missing:
        bad_rows.update(range(len(table.rows)))
    valid = [r.copy() for i, r in enumerate(table.rows) if i not in bad_rows]
    invalid = [r.copy() for i, r in enumerate(table.rows) if i in bad_rows]
    return {"validos": copy_table(table, valid), "invalidos": copy_table(table, invalid)}, issues, {
        "validas": len(valid), "invalidas": len(invalid),
        "filas_no_tabulares": sum(i["codigo"] == "ancho_incorrecto" for i in table.issues)}


SCHEMAS = {
    "select": ({"op", "columns"}, {"columns"}),
    "filter": ({"op", "column", "operator", "value", "type", "decimal", "date_format"}, {"column", "operator", "value"}),
    "sort": ({"op", "columns", "descending", "type", "decimal", "date_format"}, {"columns"}),
    "convert": ({"op", "column", "type", "decimal", "date_format"}, {"column", "type"}),
    "deduplicate": ({"op", "keys"}, {"keys"}),
    "group": ({"op", "by", "aggregates", "decimal"}, {"by", "aggregates"}),
    "rename": ({"op", "columns"}, {"columns"}),
    "normalize": ({"op", "columns", "case"}, {"columns"}),
    "replace": ({"op", "column", "map", "unknown"}, {"column", "map", "unknown"}),
}


def exact_sum(nums):
    # Precisión suficiente para todos los dígitos y el acarreo de la suma.
    least_exp = min(n.as_tuple().exponent for n in nums)
    most_digits = max(n.adjusted() for n in nums) + 1
    with localcontext() as context:
        context.prec = max(28, most_digits - least_exp + len(str(len(nums))) + 2)
        return sum(nums, Decimal(0))


def typed(value, kind, opts):
    if empty(value):
        return None
    result = convert(value, kind, opts)
    return Decimal(result) if kind in ("number", "integer") else result


def column_list(value, what="columnas"):
    if not isinstance(value, list) or not value or not all(isinstance(c, str) and c for c in value):
        raise ValueError(f"Se esperaba una lista no vacía de {what}")
    if len(set(value)) != len(value):
        raise ValueError(f"Lista de {what} duplicadas")


def check_step(step, opts):
    """Comprobación de un paso de plan sin datos (estructura, parámetros, valores admitidos).
    La usan transformar y la validación de recetas: una sola definición de lo aceptado.
    Devuelve las opciones locales del paso. Las columnas se comprueban al ejecutar."""
    if not isinstance(step, dict) or step.get("op") not in SCHEMAS:
        raise ValueError("Operación desconocida; no se admiten expresiones ni código")
    op = step["op"]
    allowed, required = SCHEMAS[op]
    if set(step) - allowed or not required <= set(step):
        raise ValueError(f"Parámetros inválidos para {op}")
    local = replace(opts, decimal=step.get("decimal", opts.decimal),
                    date_format=step.get("date_format", opts.date_format))
    if local.decimal not in (".", ",") or step.get("type", "string") not in TYPES:
        raise ValueError("Tipo o separador decimal inválido")
    if op in ("select", "sort"):
        column_list(step["columns"])
    if op == "deduplicate":
        column_list(step["keys"])
    if op == "filter":
        if not isinstance(step["column"], str):
            raise ValueError("column debe ser texto")
        if step["operator"] not in {"eq", "ne", "gt", "ge", "lt", "le", "contains"}:
            raise ValueError("Operador de filtro no admitido")
        if step["operator"] == "contains" and step.get("type", "string") != "string":
            raise ValueError("contains requiere string")
    if op == "replace":
        if not isinstance(step["column"], str) or not step["column"]:
            raise ValueError("replace: column debe ser texto")
        if not isinstance(step["map"], dict) or not step["map"] or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in step["map"].items()):
            raise ValueError("replace: map es un objeto no vacío {\"valor\": \"equivalente\"} de textos")
        if step["unknown"] not in ("keep", "exclude", "error"):
            raise ValueError("replace: unknown debe ser keep (conservar con advertencia), exclude (apartar la "
                             "fila) o error (detener)")
    if op == "normalize":
        column_list(step["columns"])
        if step.get("case", "keep") not in ("keep", "upper", "lower"):
            raise ValueError("normalize: case admite \"upper\" o \"lower\" (o se omite)")
    if op == "rename":
        mapping = step["columns"]
        if not isinstance(mapping, dict) or not mapping or not all(
                isinstance(k, str) and k and isinstance(v, str) and v.strip() for k, v in mapping.items()):
            raise ValueError("rename: columns es un objeto {\"columna actual\": \"nombre nuevo\"} no vacío")
        targets = list(mapping.values())
        repeated = sorted({t for t in targets if targets.count(t) > 1})
        if repeated:
            raise ValueError("rename: dos columnas recibirían el mismo nombre: " + ", ".join(repeated)[:120])
    if op == "sort" and not isinstance(step.get("descending", False), bool):
        raise ValueError("descending debe ser booleano")
    if op == "group":
        by, aggregates = step["by"], step["aggregates"]
        if by != []:
            if not isinstance(by, list) or not by:
                raise ValueError("by debe ser lista de columnas; [] agrupa todas")
            column_list(by)
        if not isinstance(aggregates, list) or not aggregates:
            raise ValueError("aggregates debe ser una lista no vacía")
        names = list(by)
        for spec in aggregates:
            if not isinstance(spec, dict) or set(spec) - {"op", "column", "as"} or not {"op", "as"} <= set(spec):
                raise ValueError("Agregado: op, column y as")
            if spec["op"] not in {"count", "sum", "mean", "min", "max"}:
                raise ValueError("Agregado desconocido")
            if spec["op"] != "count" and not isinstance(spec.get("column"), str):
                raise ValueError("sum, mean, min y max requieren column")
            if not isinstance(spec["as"], str) or not spec["as"].strip() or spec["as"] in names:
                raise ValueError("Alias de agregado vacío o duplicado")
            names.append(spec["as"])
    return local


def check_plan(plan, opts):
    if not isinstance(plan, dict) or set(plan) != {"steps"} or not isinstance(plan["steps"], list):
        raise ValueError("Plan: objeto con steps (lista de operaciones)")
    for number_, step in enumerate(plan["steps"], 1):
        try:
            check_step(step, opts)
        except ValueError as exc:
            raise ValueError(f"Plan, paso {number_}: {exc}") from exc


def new_trace():
    """Registro opcional de transform (lo usan las recetas): filas excluidas por filtro o
    deduplicación, celdas cambiadas por convert y filas que participan en cada grupo."""
    return {"excluidas": [], "cambios": [], "participantes": []}


def transform(table, plan, opts, trace=None):
    check_plan(plan, opts)
    if table.issues:
        return {}, table.issues, {"transformacion_bloqueada": True}
    current = copy_table(table, [r.copy() for r in table.rows])
    history = []
    warnings: list[dict] = []  # p. ej. valor_sin_equivalencia de replace con unknown keep
    for index, step in enumerate(plan["steps"], 1):
        op = step["op"]
        local = check_step(step, opts)
        count_before = len(current.rows)
        if op == "select":
            require_columns(current, step["columns"])
            selected = []
            for r in current.rows:
                row = {c: r[c] for c in step["columns"]}
                if ORIGEN in r:
                    row[ORIGEN] = r[ORIGEN]
                selected.append(row)
            current = copy_table(current, selected, step["columns"])
        elif op == "filter":
            col, operator = step["column"], step["operator"]
            require_columns(current, [col])
            kind = step.get("type", "string")
            target = typed(step["value"], kind, local)
            kept = []
            for row in current.rows:
                value = typed(row[col], kind, local)
                if operator == "eq":
                    accept = value == target
                elif operator == "ne":
                    accept = value != target
                elif value is None or target is None:
                    accept = False
                elif operator == "contains":
                    accept = target in value
                elif operator == "gt":
                    accept = value > target
                elif operator == "ge":
                    accept = value >= target
                elif operator == "lt":
                    accept = value < target
                else:
                    accept = value <= target
                if accept:
                    kept.append(row)
                elif trace is not None:
                    trace["excluidas"].append((index, "filter", f"no cumple {col} {operator} {step['value']}", row))
            current.rows = kept
        elif op == "sort":
            require_columns(current, step["columns"])

            def sortkey(row):
                values = [typed(row[c], step.get("type", "string"), local) for c in step["columns"]]
                return tuple((v is None, v) for v in values)
            current.rows.sort(key=sortkey, reverse=step.get("descending", False))
        elif op == "convert":
            require_columns(current, [step["column"]])
            col = step["column"]
            for row in current.rows:
                before = row[col]
                row[col] = convert(before, step["type"], local)
                if trace is not None and row[col] != before:
                    trace["cambios"].append((index, f"convert {step['type']}", col, before, row[col], row.get(ORIGEN)))
        elif op == "deduplicate":
            require_columns(current, step["keys"])
            seen: dict[tuple, dict] = {}
            kept = []
            for row in current.rows:
                key = tuple(row[c] for c in step["keys"])
                if key not in seen:
                    kept.append(row)
                    seen[key] = row
                elif trace is not None:
                    first = seen[key].get(ORIGEN)
                    where = f"{first[0]} fila {first[2]}" if first else "una fila anterior"
                    trace["excluidas"].append((index, "deduplicate", "repite la clave " + ", ".join(step["keys"])
                                               + f" de la fila conservada ({where})", row))
            current.rows = kept
        elif op == "group":
            by, aggregates = step["by"], step["aggregates"]
            if by:
                require_columns(current, by)
            names = list(by)
            for spec in aggregates:
                if spec["op"] != "count" or "column" in spec:
                    require_columns(current, [spec.get("column")])
                names.append(spec["as"])
            groups: dict[tuple, list[dict[str, Any]]] = {}
            for row in current.rows:
                groups.setdefault(tuple(row[c] for c in by), []).append(row)
            output = []
            for key, rows in groups.items():
                result = dict(zip(by, key, strict=True))
                if trace is not None:
                    trace["participantes"].extend((index, key, r.get(ORIGEN)) for r in rows)
                for spec in aggregates:
                    agg = spec["op"]
                    if agg == "count":
                        result[spec["as"]] = str(len(rows) if "column" not in spec else sum(not empty(r[spec["column"]]) for r in rows))
                        continue
                    nums = [number(r[spec["column"]], local.decimal) for r in rows if not empty(r[spec["column"]])]
                    if not nums:
                        val = None
                    elif agg == "sum":
                        val = exact_sum(nums)
                    elif agg == "mean":
                        val = exact_sum(nums) / len(nums)
                    elif agg == "min":
                        val = min(nums)
                    else:
                        val = max(nums)
                    result[spec["as"]] = None if val is None else format(val, "f")
                output.append(result)
            current = copy_table(current, output, names)
        unified: dict[str, int] = {}
        if op == "normalize":
            require_columns(current, step["columns"])
            case = step.get("case", "keep")
            label = "normalize" + ("" if case == "keep" else " " + case)
            for col in step["columns"]:
                distinct_before = {r[col] for r in current.rows if not empty(r[col])}
                for row in current.rows:
                    before = row[col]
                    if before is None:
                        continue
                    # Espacios en blanco (incluido el no separable y el tabulador): fuera los extremos y
                    # cada racha interior queda en un espacio. Sin tocar tildes ni convertir tipos.
                    after = " ".join(str(before).split())
                    after = after.upper() if case == "upper" else after.lower() if case == "lower" else after
                    if after != before:
                        row[col] = after
                        if trace is not None:
                            trace["cambios"].append((index, label, col, before, after, row.get(ORIGEN)))
                merged = len(distinct_before) - len({r[col] for r in current.rows if not empty(r[col])})
                if merged:
                    unified[col] = merged  # valores distintos que pasaron a ser iguales: posibles claves unidas
        if op == "replace":
            col, mapping, unknown = step["column"], step["map"], step["unknown"]
            require_columns(current, [col])
            canonical = set(mapping.values())  # un valor que ya es destino del mapa no es desconocido
            kept = []
            for position, row in enumerate(current.rows):
                value = row[col]
                if isinstance(value, str) and value in mapping:  # coincidencia exacta, sin aproximaciones
                    if mapping[value] != value:
                        row[col] = mapping[value]
                        if trace is not None:
                            trace["cambios"].append((index, "replace", col, value, row[col], row.get(ORIGEN)))
                elif not empty(value) and value not in canonical:
                    if unknown == "error":
                        raise ValueError(f"replace: valor sin equivalencia en {col} (paso {index} del plan); "
                                         "amplíe el mapa o elija unknown keep/exclude")
                    if unknown == "exclude":
                        if trace is not None:
                            trace["excluidas"].append((index, "replace", f"valor sin equivalencia en {col}", row))
                        continue
                    origin = row.get(ORIGEN)
                    warnings.append({"origen": origin[1] if origin else table.source, "codigo": "valor_sin_equivalencia",
                                     "columna": col, "fila": origin[2] if origin else position + 2})
                kept.append(row)
            current.rows = kept
        if op == "rename":
            mapping = step["columns"]
            require_columns(current, list(mapping))
            names = [mapping.get(c, c) for c in current.columns]
            clash = sorted({n for n in names if names.count(n) > 1})
            if clash:
                raise ValueError("rename: el nombre nuevo choca con una columna existente: " + ", ".join(clash)[:120])
            # La procedencia interna no está en el mapeo: se conserva tal cual.
            current = copy_table(current, [{mapping.get(k, k): v for k, v in r.items()} for r in current.rows], names)
        history.append({"operacion": op, "antes": count_before, "despues": len(current.rows),
                        **({"renombradas": step["columns"]} if op == "rename" else {}),
                        **({"valores_unificados": unified} if unified else {})})
    details = {"filas_salida": len(current.rows), "pasos": history}
    if warnings:  # solo si hay: la salida de los planes anteriores no cambia
        details["advertencias"] = warnings
    return {"validos": current}, [], details


ENRICH_CODES = {"sin_coincidencia": "clave_sin_coincidencia", "ambiguas": "coincidencia_ambigua",
                "clave_vacia": "clave_vacia"}


def enrich(table, reference, keys, ref_keys, columns, existing="error"):
    """Completa `columns` desde `reference` por clave exacta de texto ("0007" no es "7").
    Cada fila de entrada va a una sola salida: completadas, sin_coincidencia, ambiguas o clave_vacia.
    Nunca elige entre varias coincidencias ni multiplica filas. Devuelve (tablas, incidencias de
    la entrada, incidencias de la referencia, cambios de celdas, detalle)."""
    require_columns(table, keys)
    require_columns(reference, ref_keys)
    require_columns(reference, columns)
    if len(keys) != len(ref_keys):
        raise ValueError("clave y clave_referencia deben tener el mismo número de columnas")
    if set(columns) & set(ref_keys):
        raise ValueError("Las columnas a incorporar no pueden ser parte de la clave de la referencia")
    present = [c for c in columns if c in table.columns]
    if present and existing == "error":
        raise ValueError("Columnas ya presentes en la entrada: " + ", ".join(present)[:120] + ". Para no pisar datos "
                         "sin querer indique \"existentes\": \"completar_vacios\" o \"reemplazar\"")
    label = ",".join(ref_keys)
    ref_issues: list[dict] = []
    index: dict[tuple, list[tuple[int, dict]]] = {}
    for rowno, row in zip(reference.row_numbers or range(2, len(reference.rows) + 2), reference.rows, strict=True):
        key = tuple(row[c] for c in ref_keys)
        if any(empty(v) for v in key):
            ref_issues.append(issue("clave_vacia_en_referencia", rowno, label, reference.source))
        else:
            index.setdefault(key, []).append((rowno, row))
    for matches in index.values():
        if len(matches) > 1:
            ref_issues.extend(issue("clave_duplicada_en_referencia", rowno, label, reference.source,
                                    f"{len(matches)} filas con la misma clave") for rowno, _ in matches)
    buckets: dict[str, list[dict]] = {"completadas": [], "sin_coincidencia": [], "ambiguas": [], "clave_vacia": []}
    issues: list[dict] = []
    changes: list[tuple] = []
    counts: Counter = Counter()
    for rowno, row in zip(table.row_numbers or range(2, len(table.rows) + 2), table.rows, strict=True):
        key = tuple(row[c] for c in keys)
        matches = index.get(key, [])
        bucket = ("clave_vacia" if any(empty(v) for v in key) else "sin_coincidencia" if not matches
                  else "ambiguas" if len(matches) > 1 else "completadas")
        if bucket != "completadas":
            issues.append(issue(ENRICH_CODES[bucket], rowno, ",".join(keys), table.source,
                                f"{len(matches)} coincidencias en la referencia" if bucket == "ambiguas" else None))
            buckets[bucket].append(row.copy())
            continue
        new, match = row.copy(), matches[0][1]
        for col in columns:
            value = match[col]
            if col not in table.columns:
                new[col] = value
                continue
            before = new[col]
            fill = existing == "completar_vacios" and empty(before) and not empty(value)
            if (existing == "reemplazar" and before != value) or fill:
                new[col] = value
                counts["celdas_completadas" if fill else "celdas_reemplazadas"] += 1
                changes.append(("", f"completar ({existing})", col, before, value, row.get(ORIGEN)))
            elif existing == "completar_vacios" and not empty(before) and before != value:
                counts["celdas_presentes_distintas"] += 1  # se conserva el dato presente
        buckets["completadas"].append(new)
    out_columns = table.columns + [c for c in columns if c not in table.columns]
    tables = {name: copy_table(table, rows, out_columns if name == "completadas" else None)
              for name, rows in buckets.items()}
    details = {**{name: len(rows) for name, rows in buckets.items()},
               "celdas_completadas": counts["celdas_completadas"], "celdas_reemplazadas": counts["celdas_reemplazadas"],
               "celdas_presentes_distintas": counts["celdas_presentes_distintas"],
               "claves_duplicadas_en_referencia": sum(len(m) > 1 for m in index.values())}
    return tables, issues, ref_issues, changes, details


def split_duplicates(table, keys, keep="ninguno", date=None, tie="conflicto", compare_columns=None, opts=None):
    """Separa filas por clave en conservadas, excluidas y conflictos (invariante: entrada = suma).
    - Copias idénticas (en compare_columns) de otra fila: excluidas, siempre.
    - Misma clave con valores distintos: conflicto, salvo política explícita keep = primero,
      ultimo o mas_reciente (fecha válida; empate según tie, por defecto conflicto).
    - Clave vacía: conflicto. Devuelve (tablas, incidencias, motivos por origen, detalle)."""
    require_columns(table, keys)
    columns = compare_columns or [c for c in table.columns if not c.startswith("__")]
    require_columns(table, columns)
    if keep == "mas_reciente":
        require_columns(table, [date])
    numbers = table.row_numbers or list(range(2, len(table.rows) + 2))

    def label(pos):
        origin = table.rows[pos].get(ORIGEN)
        return f"{origin[0]} fila {origin[2]}" if origin else f"fila {numbers[pos]}"

    def values(pos):
        return tuple(table.rows[pos][c] for c in columns)

    groups: dict[tuple, list[int]] = {}
    for pos, row in enumerate(table.rows):
        groups.setdefault(tuple(row[c] for c in keys), []).append(pos)
    fate: dict[int, tuple[str, str | None]] = {}
    for key, positions in groups.items():
        if any(empty(v) for v in key):
            fate.update({p: ("conflictos", "clave vacía: no se puede comparar") for p in positions})
            continue
        distinct: list[int] = []
        for p in positions:
            twin = next((d for d in distinct if values(d) == values(p)), None)
            if twin is None:
                distinct.append(p)
            else:
                fate[p] = ("excluidas", f"idéntica a {label(twin)}")
        if len(distinct) == 1:
            fate[distinct[0]] = ("conservadas", None)
            continue
        what = "misma clave con valores distintos en: " + ", ".join(
            c for c in columns if len({table.rows[d][c] for d in distinct}) > 1)
        winner, reason = None, None
        if keep == "primero":
            winner = distinct[0]
        elif keep == "ultimo":
            winner = distinct[-1]
        elif keep == "mas_reciente":
            try:
                dates = [typed(table.rows[d][date], "date", opts) for d in distinct]
            except ValueError:
                dates = [None]
            if any(v is None for v in dates):
                reason = f"fecha vacía o inválida en {date}"
            else:
                top = max(dates)
                tied = [d for d, v in zip(distinct, dates, strict=True) if v == top]
                if len(tied) == 1 or tie != "conflicto":
                    winner = tied[0] if len(tied) == 1 or tie == "primero" else tied[-1]
                else:
                    reason = f"empate en la fecha más reciente ({date})"
        if winner is None:
            fate.update({d: ("conflictos", what + (f"; {reason}" if reason else "")) for d in distinct})
        else:
            fate[winner] = ("conservadas", None)
            fate.update({d: ("excluidas", f"{what}; política {keep}: se conservó {label(winner)}")
                         for d in distinct if d != winner})
    buckets: dict[str, list[dict]] = {"conservadas": [], "excluidas": [], "conflictos": []}
    issues: list[dict] = []
    motives: dict[tuple, list[str]] = {}
    for pos, row in enumerate(table.rows):
        bucket, why = fate[pos]
        buckets[bucket].append(row.copy())
        origin = row.get(ORIGEN)
        if why and origin:
            motives[origin[1:]] = [why]
        if bucket == "conflictos":
            issues.append(issue("clave_vacia" if why and why.startswith("clave vacía") else "conflicto_de_duplicados",
                                numbers[pos], ",".join(keys), table.source))
    tables = {name: copy_table(table, rows) for name, rows in buckets.items()}
    return tables, issues, motives, {name: len(rows) for name, rows in buckets.items()}


def merge_tables(items):
    """Une tablas con las mismas columnas (en cualquier orden) y añade procedencia.
    items: lista de (origen, Table o None, error de lectura). Una tabla con incidencias,
    sin columnas o con columnas de procedencia reservadas se rechaza completa."""
    columns = None
    rows: list[dict] = []
    issues: list[dict] = []
    accepted: list[str] = []
    rejected: list[str] = []
    for source, table, read_error in items:
        if table is None:
            issues.append(issue("archivo_ilegible", source=source, detail=read_error))
            rejected.append(source)
            continue
        if table.issues or not table.columns or "__archivo_origen" in table.columns or "__fila_origen" in table.columns:
            issues.extend(table.issues or [issue("columna_procedencia_reservada", source=source)])
            rejected.append(source)
            continue
        if columns is None:
            columns = table.columns
        if set(columns) != set(table.columns):
            issues.append(issue("columnas_incompatibles", source=source, detail=json.dumps({
                "faltantes": sorted(set(columns) - set(table.columns)),
                "adicionales": sorted(set(table.columns) - set(columns))}, ensure_ascii=False)))
            rejected.append(source)
            continue
        accepted.append(source)
        numbers = table.row_numbers or list(range(2, len(table.rows) + 2))
        for rowno, row in zip(numbers, table.rows, strict=True):
            # En recetas la fila trae su procedencia real; si no, la de esta tabla.
            origin = row.get(ORIGEN)
            rows.append({**row, "__archivo_origen": origin[1] if origin else source,
                         "__fila_origen": str(origin[2] if origin else rowno)})
    if not items:
        issues.append(issue("sin_archivos_compatibles"))
    output = Table((columns or []) + ["__archivo_origen", "__fila_origen"], rows)
    return output, issues, {"aceptados": accepted, "rechazados": rejected, "filas_salida": len(rows)}


def query_warnings(details, source):
    """Advertencias de consultar a partir de sus conteos (CLI y recetas)."""
    found = []
    if details["valores_no_numericos"]:
        found.append({"origen": source, "codigo": "valores_no_numericos_cargados_como_null"})
    if details["valores_redondeados"]:
        found.append({"origen": source, "codigo": "numeros_redondeados_por_precision_real"})
    if details["columnas_sin_numeric"]:
        found.append({"origen": source, "codigo": "resultado_depende_de_texto_sin_numeric",
                      "columnas": details["columnas_sin_numeric"]})
    return found


SQL_ALLOWED = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _real(value, decimal):
    """(float, estado) para una celda no vacía de --numeric. Estados: None, desbordamiento,
    subdesbordamiento (no nulo que quedaría en cero) o redondeo (más cifras de las que guarda REAL)."""
    exact = number(value, decimal)
    real = float(exact)
    if math.isinf(real):
        return real, "desbordamiento"
    if real == 0 and exact != 0:
        return real, "subdesbordamiento"
    if len(exact.as_tuple().digits) > 15 and Decimal(repr(real)) != exact:
        return real, "redondeo"
    return real, None


def _decimal_text_columns(tables, numeric, opts, read):
    """Columnas de texto que parecen medidas: la mayoría de sus valores no vacíos son números
    según --decimal, alguno con decimales, y ninguno es un código con ceros iniciales."""
    found = set()
    for name, table in tables.items():
        for col in table.columns:
            if col in numeric or (name.lower(), col.lower()) not in read:
                continue
            filled = numbers = fractions = 0
            for value in {r[col] for r in table.rows}:
                if empty(value):
                    continue
                filled += 1
                text = str(value).strip()
                if re.fullmatch(r"[+-]?0\d+", text):
                    break
                try:
                    number(text, opts.decimal)
                except ValueError:
                    continue
                numbers += 1
                fractions += opts.decimal in text
            else:
                if fractions and numbers * 2 > filled:
                    found.add((name.lower(), col.lower()))
    return found


def _load(tables, numeric, opts, strict):
    """Base en memoria con las columnas de `numeric` como REAL. `strict` cuenta y rechaza pérdidas de rango."""
    db = sqlite3.connect(":memory:")
    counts: Counter = Counter()
    try:
        for name, table in tables.items():
            reals = [(name.lower(), c.lower()) in numeric for c in table.columns]
            db.execute("CREATE TABLE {} ({})".format(_quote(name), ", ".join(
                _quote(c) + (" REAL" if real else " TEXT") for c, real in zip(table.columns, reals, strict=True))))
            rows = []
            for row in table.rows:
                values = []
                for col, real in zip(table.columns, reals, strict=True):
                    value = row[col]
                    if real:
                        if empty(value):
                            value = None
                        else:
                            try:
                                value, state = _real(value, opts.decimal)
                            except ValueError:
                                value, state = None, "no_numerico"
                            if state:
                                counts[(state, name, col)] += 1
                    values.append(value)
                rows.append(values)
            db.executemany("INSERT INTO {} VALUES ({})".format(_quote(name), ", ".join("?" * len(table.columns))), rows)
        lost = [(k, n) for k, n in counts.items() if k[0] in ("desbordamiento", "subdesbordamiento")]
        if strict and lost:
            # Nombres y conteos; nunca el contenido de las celdas.
            raise ValueError("Valores de --numeric fuera del rango representable: " + "; ".join(
                f"tabla {k[1]}, columna {k[2][:40]}: {n} por {k[0]}" for k, n in lost[:2])
                + ". No se publicó ningún resultado; para esos valores use transformar (Decimal).")
        db.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in SQL_ALLOWED else sqlite3.SQLITE_DENY)
    except BaseException:
        db.close()
        raise
    return db, counts


def _same_number(a, b):
    return a == b or (isinstance(a, float) and isinstance(b, float) and math.isclose(a, b, rel_tol=1e-9))


def _comparable(record, opts):
    """Fila con los textos numéricos (según --decimal) llevados a float, para comparar dos ejecuciones."""
    output = []
    for value in record:
        if isinstance(value, str):
            try:
                value = float(number(value, opts.decimal))
            except ValueError:
                pass
        elif isinstance(value, int):
            value = float(value)
        output.append(value)
    return output


def query(tables, sql, numeric, opts, trace=None):
    """Una consulta SELECT sobre tablas cargadas en SQLite en memoria; nada se escribe ni se adjunta.
    trace (solo recetas) recibe las tablas que la consulta leyó; el uso suelto no cambia su salida."""
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("--sql requiere una consulta SELECT")
    known = {c for table in tables.values() for c in table.columns}
    if set(numeric) - known:
        raise ValueError("Columnas de --numeric inexistentes: " + ", ".join(sorted(set(numeric) - known)))
    issues: list[dict] = []
    for name, table in tables.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,40}", name):
            raise ValueError("Nombre de tabla: letras ASCII, dígitos y guion bajo, sin empezar por dígito")
        if not table.columns:
            raise ValueError(f"La tabla {name} no tiene encabezado legible")
        issues.extend(table.issues)
    declared = {(name.lower(), c.lower()) for name, table in tables.items() for c in table.columns if c in numeric}
    read: set[tuple[str, str]] = set()

    def authorize(action, first, second, *_):
        if action == sqlite3.SQLITE_READ and first and second:
            read.add((first.lower(), second.lower()))
        return sqlite3.SQLITE_OK if action in SQL_ALLOWED else sqlite3.SQLITE_DENY

    try:
        db, counts = _load(tables, declared, opts, strict=True)
        try:
            db.set_authorizer(authorize)
            cursor = db.execute(sql)
            if cursor.description is None:
                raise ValueError("Solo se admite una consulta SELECT")
            names: list[str] = []
            for item in cursor.description:
                base = item[0] or "columna"
                name, n = base, 2
                while name in names:
                    name, n = f"{base}_{n}", n + 1
                names.append(name)
            records = cursor.fetchall()
        finally:
            db.close()
    except sqlite3.Error as exc:
        raise ValueError("SQL no válido o no permitido: " + str(exc)[:160]) from exc
    # Un resultado infinito o NaN no tiene texto decimal: se rechaza en vez de publicarlo.
    bad = sorted({names[i][:40] for record in records for i, v in enumerate(record)
                  if isinstance(v, float) and not math.isfinite(v)})
    if bad:
        raise ValueError("El resultado tiene valores fuera del rango representable (desbordamiento) en: "
                         + ", ".join(bad[:5]) + ". No se publicó ningún resultado; para sumas exactas use transformar.")
    output = [dict(zip(names, [real_text(v) if isinstance(v, float) else literal(v) for v in record], strict=True))
              for record in records]
    # Protección ante la omisión de --numeric: si la consulta lee columnas de texto con decimales,
    # se repite con ellas como número. Un resultado distinto significa que SQLite las usó como
    # texto en un cálculo, comparación u orden. No se analiza el SQL ni se cambia lo publicado.
    suspects = sorted(_decimal_text_columns(tables, numeric, opts, read))
    undeclared: list[str] = []
    if suspects:
        try:
            shadow, _ = _load(tables, declared | set(suspects), opts, strict=False)
            try:
                other = shadow.execute(sql).fetchall()
            finally:
                shadow.close()
            same = len(other) == len(records) and all(
                len(a) == len(b) and all(_same_number(x, y) for x, y in zip(_comparable(a, opts), _comparable(b, opts), strict=True))
                for a, b in zip(records, other, strict=True))
        except (sqlite3.Error, ValueError, OverflowError):
            same = False
        if not same:
            originals = {(n.lower(), c.lower()): c for n, table in tables.items() for c in table.columns}
            undeclared = sorted({originals[key] for key in suspects})

    def total(state):
        return sum(n for key, n in counts.items() if key[0] == state)

    if trace is not None:
        trace["tablas_leidas"] = sorted({t for t, _ in read})
    return {"validos": Table(names, output)}, issues, {
        "filas_salida": len(output), "valores_no_numericos": total("no_numerico"),
        "valores_redondeados": total("redondeo"), "columnas_sin_numeric": undeclared}

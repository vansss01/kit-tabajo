"""Operaciones declarativas; no eval, exec, SQL ni expresiones de Python."""
import json
from collections import Counter
from dataclasses import replace
from decimal import Decimal, localcontext
from typing import Any

from kitlib.tableio import Table, convert, empty, infer, issue, number

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
            "columnas": stats, "muestra": table.rows[:sample],
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
    allowed = {"required", "nonempty", "unique", "type", "min", "max", "date_format", "decimal"}
    for col, spec in config["columns"].items():
        if not isinstance(spec, dict) or set(spec) - allowed:
            raise ValueError(f"Regla inválida en {col}")
        if spec.get("type", "string") not in TYPES:
            raise ValueError(f"Tipo desconocido en {col}")
        for flag in ("required", "nonempty", "unique"):
            if flag in spec and not isinstance(spec[flag], bool):
                raise ValueError(f"{flag} debe ser booleano")
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


def transform(table, plan, opts):
    if set(plan) != {"steps"} or not isinstance(plan["steps"], list):
        raise ValueError("Plan: objeto con steps (lista de operaciones)")
    if table.issues:
        return {}, table.issues, {"transformacion_bloqueada": True}
    current = copy_table(table, [r.copy() for r in table.rows])
    history = []
    for step in plan["steps"]:
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
        count_before = len(current.rows)
        if op == "select":
            require_columns(current, step["columns"])
            current = copy_table(current, [{c: r[c] for c in step["columns"]} for r in current.rows], step["columns"])
        elif op == "filter":
            col, operator = step["column"], step["operator"]
            require_columns(current, [col])
            if operator not in {"eq", "ne", "gt", "ge", "lt", "le", "contains"}:
                raise ValueError("Operador de filtro no admitido")
            kind = step.get("type", "string")
            if operator == "contains" and kind != "string":
                raise ValueError("contains requiere string")
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
            current.rows = kept
        elif op == "sort":
            require_columns(current, step["columns"])
            if not isinstance(step.get("descending", False), bool):
                raise ValueError("descending debe ser booleano")
            def sortkey(row):
                values = [typed(row[c], step.get("type", "string"), local) for c in step["columns"]]
                return tuple((v is None, v) for v in values)
            current.rows.sort(key=sortkey, reverse=step.get("descending", False))
        elif op == "convert":
            require_columns(current, [step["column"]])
            for row in current.rows:
                row[step["column"]] = convert(row[step["column"]], step["type"], local)
        elif op == "deduplicate":
            require_columns(current, step["keys"])
            seen = set()
            kept = []
            for row in current.rows:
                key = tuple(row[c] for c in step["keys"])
                if key not in seen:
                    kept.append(row)
                    seen.add(key)
            current.rows = kept
        elif op == "group":
            by, aggregates = step["by"], step["aggregates"]
            if by:
                require_columns(current, by)
            elif by != []:
                raise ValueError("by debe ser lista de columnas; [] agrupa todas")
            if not isinstance(aggregates, list) or not aggregates:
                raise ValueError("aggregates debe ser una lista no vacía")
            names = list(by)
            for spec in aggregates:
                if not isinstance(spec, dict) or set(spec) - {"op", "column", "as"} or not {"op", "as"} <= set(spec):
                    raise ValueError("Agregado: op, column y as")
                if spec["op"] not in {"count", "sum", "mean", "min", "max"}:
                    raise ValueError("Agregado desconocido")
                if spec["op"] != "count" or "column" in spec:
                    require_columns(current, [spec.get("column")])
                if not isinstance(spec["as"], str) or not spec["as"].strip() or spec["as"] in names:
                    raise ValueError("Alias de agregado vacío o duplicado")
                names.append(spec["as"])
            groups: dict[tuple, list[dict[str, Any]]] = {}
            for row in current.rows:
                groups.setdefault(tuple(row[c] for c in by), []).append(row)
            output = []
            for key, rows in groups.items():
                result = dict(zip(by, key, strict=True))
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
        history.append({"operacion": op, "antes": count_before, "despues": len(current.rows)})
    return {"validos": current}, [], {"filas_salida": len(current.rows), "pasos": history}

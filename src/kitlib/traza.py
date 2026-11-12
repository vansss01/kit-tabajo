"""Trazabilidad de las recetas: procedencia real de cada fila, filas excluidas, cambios de celdas,
participación en agregados e invariantes por operación.

La procedencia viaja dentro de cada fila bajo `tableio.ORIGEN` como (entrada, archivo, fila lógica
del archivo original). Aquí solo se escribe en archivos auxiliares; las tablas de negocio no la
llevan. Todo lo escrito queda en la carpeta del paso; la terminal solo ve conteos.
"""
import json
from collections import Counter

from kitlib.tableio import ORIGEN, Table, csv_write, public_row

ORIGIN_COLUMNS = ["entrada", "archivo", "fila_origen"]


def tag(table, entry, path):
    """Marca cada fila leída de una entrada con su procedencia real."""
    numbers = table.row_numbers or list(range(2, len(table.rows) + 2))
    for rowno, row in zip(numbers, table.rows, strict=True):
        row[ORIGEN] = (entry, str(path), rowno)


def _origin(origin):
    return [origin[0], origin[1], str(origin[2])] if origin else ["", "", ""]


def origins(table):
    return [row.get(ORIGEN) for row in table.rows]


def remap_issues(issues, table):
    """Las incidencias de validar citan la fila de la tabla validada; si esa tabla viene de un paso
    anterior, se reemplaza por el archivo y la fila originales."""
    numbers = table.row_numbers or list(range(2, len(table.rows) + 2))
    by_number = dict(zip(numbers, table.rows, strict=True))
    output = []
    for item in issues:
        row = by_number.get(item["fila"])
        origin = row.get(ORIGEN) if row is not None else None
        output.append({**item, "fila": origin[2], "origen": origin[1]} if origin else item)
    return output


def write_provenance(folder, name, table, delimiter, motives=None):
    """`<name>_procedencia.csv`: una línea por fila de la tabla (fila 2 = primera de datos).
    Devuelve el nombre del archivo y cuántas filas no tienen procedencia individual."""
    rows, missing = [], 0
    for number, row in enumerate(table.rows, 2):
        origin = row.get(ORIGEN)
        missing += origin is None
        values = [str(number), *_origin(origin)]
        if motives is not None:
            values.append(" ".join(motives.get(origin[1:] if origin else None, [])))
        rows.append(values)
    columns = ["fila", *ORIGIN_COLUMNS] + (["motivos"] if motives is not None else [])
    csv_write(folder / f"{name}_procedencia.csv", Table(columns, [dict(zip(columns, r, strict=True)) for r in rows]),
              delimiter)
    return f"{name}_procedencia.csv", missing


def motives_by_origin(issues):
    """Códigos de incidencia por (archivo, fila) original, para la procedencia de rechazadas."""
    found: dict = {}
    for item in issues:
        if item.get("fila") is not None:
            found.setdefault((item["origen"], item["fila"]), set()).add(item["codigo"])
    return {k: sorted(v) for k, v in found.items()}


def write_excluded(folder, trace, delimiter):
    """`excluidas.csv`: filas que un filtro o una deduplicación dejó fuera, con su motivo y la
    fila tal como estaba en ese momento del plan."""
    business: list[str] = []
    for *_, row in trace["excluidas"]:
        business.extend(c for c in public_row(row) if c not in business)
    columns = ["paso_plan", "operacion", "motivo", *ORIGIN_COLUMNS, *business]
    rows = [dict(zip(columns, [str(i), op, why, *_origin(row.get(ORIGEN)),
                               *(public_row(row).get(c) for c in business)], strict=True))
            for i, op, why, row in trace["excluidas"]]
    csv_write(folder / "excluidas.csv", Table(columns, rows), delimiter)
    return "excluidas.csv"


def write_changes(folder, trace, delimiter):
    """`cambios_celdas.csv`: registro, columna, valor anterior, valor nuevo y operación."""
    columns = [*ORIGIN_COLUMNS, "columna", "valor_anterior", "valor_nuevo", "operacion", "paso_plan"]
    rows = [dict(zip(columns, [*_origin(origin), col, before, after, op, str(i)], strict=True))
            for i, op, col, before, after, origin in trace["cambios"]]
    csv_write(folder / "cambios_celdas.csv", Table(columns, rows), delimiter)
    return "cambios_celdas.csv"


def write_participants(folder, trace, by_step, delimiter):
    """`participantes.csv` (solo con "traza": "detallada"): qué fila original entra en qué grupo."""
    columns = ["paso_plan", "grupo", *ORIGIN_COLUMNS]
    rows = [dict(zip(columns, [str(i), json.dumps(dict(zip(by_step[i], key, strict=True)), ensure_ascii=False),
                               *_origin(origin)], strict=True))
            for i, key, origin in trace["participantes"]]
    csv_write(folder / "participantes.csv", Table(columns, rows), delimiter)
    return "participantes.csv"


def write_compare_changes(folder, before, after, keys, changes, delimiter):
    """`cambios_procedencia.csv`: para cada línea de cambios, la fila original de antes y de después."""
    def index(table):
        return {json.dumps(dict(zip(keys, (r[c] for c in keys), strict=True)), ensure_ascii=False): r.get(ORIGEN)
                for r in table.rows}
    left, right = index(before), index(after)
    columns = ["fila", *(c + "_antes" for c in ORIGIN_COLUMNS), *(c + "_despues" for c in ORIGIN_COLUMNS)]
    rows = [dict(zip(columns, [str(n), *_origin(left.get(r["clave"])), *_origin(right.get(r["clave"]))],
                     strict=True)) for n, r in enumerate(changes.rows, 2)]
    csv_write(folder / "cambios_procedencia.csv", Table(columns, rows), delimiter)
    return "cambios_procedencia.csv"


def _known(values):
    return Counter(v for v in values if v is not None)


def invariants(op, inputs, outputs, trace, details):
    """Igualdades que deben cumplirse en cada operación. Solo validar, consolidar y transformar sin
    agregación son particiones (entrada = salidas + apartadas). Agregados, comparaciones y SQL no."""
    if op == "validar" and outputs:
        source, ok, bad = inputs[0], outputs["aceptadas"], outputs["rechazadas"]
        holds = (len(source.rows) == len(ok.rows) + len(bad.rows)
                 and Counter(origins(source)) == Counter(origins(ok)) + Counter(origins(bad)))
        return [{"tipo": "particion", "regla": "entrada = aceptadas + rechazadas (mismas filas de origen)",
                 "entrada": len(source.rows), "aceptadas": len(ok.rows), "rechazadas": len(bad.rows),
                 "cumple": holds}]
    if op == "transformar" and outputs:
        source, out = inputs[0], outputs["resultado"]
        excluded = [row.get(ORIGEN) for *_, row in trace["excluidas"]]
        consumed = [origin for *_, origin in trace["participantes"]]
        if not trace["participantes"]:
            holds = (len(source.rows) == len(out.rows) + len(excluded)
                     and Counter(origins(source)) == Counter(origins(out)) + Counter(excluded))
            return [{"tipo": "particion", "regla": "entrada = resultado + excluidas (mismas filas de origen)",
                     "entrada": len(source.rows), "resultado": len(out.rows), "excluidas": len(excluded),
                     "cumple": holds}]
        holds = _known(origins(source)) == _known(origins(out)) + _known(excluded) + _known(consumed)
        return [{"tipo": "participacion", "regla": "cada fila de origen de la entrada termina en el resultado, en "
                 "excluidas o dentro de un grupo; no se compara la cantidad de filas del resultado",
                 "entrada": len(source.rows), "excluidas": len(excluded), "en_grupos": len(consumed),
                 "cumple": holds}]
    if op == "consolidar" and outputs:
        accepted = [t for ref, t in inputs if ref in details["aceptados"]]
        out = outputs["resultado"]
        expected: Counter = sum((Counter(origins(t)) for t in accepted), Counter())
        holds = len(out.rows) == sum(len(t.rows) for t in accepted) and Counter(origins(out)) == expected
        return [{"tipo": "particion", "regla": "resultado = filas de las tablas aceptadas; las rechazadas "
                 "quedan fuera completas", "entrada": sum(len(t.rows) for _, t in inputs),
                 "resultado": len(out.rows), "excluidas": sum(len(t.rows) for r, t in inputs if r not in
                                                              details["aceptados"]), "cumple": holds}]
    if op == "completar" and outputs:
        source = inputs[0]
        parts = ("completadas", "sin_coincidencia", "ambiguas", "clave_vacia")
        expected = sum((Counter(origins(outputs[p])) for p in parts), Counter())
        holds = (len(source.rows) == sum(len(outputs[p].rows) for p in parts)
                 and Counter(origins(source)) == expected)
        return [{"tipo": "particion", "regla": "entrada = completadas + sin_coincidencia + ambiguas + clave_vacia "
                 "(cruce sin multiplicar filas)", "entrada": len(source.rows),
                 **{p: len(outputs[p].rows) for p in parts}, "cumple": holds}]
    if op == "comparar" and outputs:
        before, after = inputs
        same = details["modificados"] + details["sin_cambios"]
        holds = (len(before.rows) == details["eliminados"] + same and len(after.rows) == details["nuevos"] + same
                 and len(outputs["nuevos"].rows) == details["nuevos"]
                 and len(outputs["eliminados"].rows) == details["eliminados"])
        return [{"tipo": "claves", "regla": "antes = eliminadas + comunes; después = nuevas + comunes (cruce, "
                 "no partición)", "antes": len(before.rows), "despues": len(after.rows), "cumple": holds}]
    if op == "exportar":
        return [{"tipo": "copia", "regla": "cada tabla exportada tiene las filas de su origen",
                 "cumple": all(len(outputs[a].rows) == len(t.rows) for a, t in inputs)}]
    return [{"tipo": "ninguna", "regla": "sin invariante de filas: " + (
        "SQL puede combinar, agrupar o repetir filas" if op == "consultar" else "solo informa"), "cumple": True}]

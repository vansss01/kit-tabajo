"""Lectura sin inferencias destructivas y escritura exclusiva de tablas."""
import contextlib
import csv
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from kitlib.runtime import inside


@dataclass
class Options:
    delimiter: str = ","
    encoding: str = "utf-8-sig"
    decimal: str = "."
    date_format: str | None = None
    sheet: str | None = None
    # Solo recetas (CSV/XLSX): fila del encabezado (las anteriores se omiten) y condiciones
    # explícitas para excluir pies o totales. Por defecto, el comportamiento de siempre.
    header_row: int = 1
    exclude_rows: tuple = ()


@dataclass
class Table:
    columns: list[str]
    rows: list[dict[str, Any]]
    source: str = ""
    sheet: str | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scanned: int = 0
    complete: bool = True
    row_numbers: list[int] = field(default_factory=list)
    excluded: list[tuple] = field(default_factory=list)  # (fila, motivo, valores) por exclude_rows


# Procedencia interna de las recetas: cada fila lleva bajo esta clave (entrada, archivo, fila lógica
# del archivo original). No es una columna: no está en Table.columns, ningún escritor la publica y
# los comandos sueltos no la usan. Empieza por \x00 para no chocar con un encabezado real.
ORIGEN = "\x00origen"


def public_row(row):
    """La fila sin la procedencia interna (para escribirla o mostrarla)."""
    return {k: v for k, v in row.items() if k != ORIGEN} if ORIGEN in row else row


def issue(code, row=None, column=None, source=None, detail=None):
    return {"codigo": code, "fila": row, "columna": column,
            "origen": source, "detalle": detail}


def empty(value):
    return value is None or (isinstance(value, str) and not value.strip())


def literal(value):
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@lru_cache(maxsize=8)
def _number_pattern(decimal):
    return re.compile(r"[+-]?(?:\d+(?:" + re.escape(decimal) + r"\d+)?|" + re.escape(decimal) + r"\d+)")


def number(value, decimal="."):
    text = str(value).strip()
    if not _number_pattern(decimal).fullmatch(text):
        raise ValueError("Número inválido; no se admiten separadores de miles ni exponentes.")
    try:
        return Decimal(text.replace(decimal, "."))
    except InvalidOperation as exc:
        raise ValueError("Número inválido") from exc


def real_text(value):
    """Texto decimal con punto y sin exponente para un float finito, sin redondeo añadido:
    los dígitos más cortos que al leerse devuelven el mismo float (repr)."""
    text = format(Decimal(repr(value)), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def convert(value, kind, opts):
    if empty(value):
        return None
    if kind == "string":
        return str(value)
    if kind in ("integer", "number"):
        n = number(value, opts.decimal)
        if kind == "integer":
            if n != n.to_integral_value():
                raise ValueError("No es un entero")
            return str(int(n))
        return format(n, "f")
    if kind == "date":
        fmt = opts.date_format or "%Y-%m-%d"
        text = str(value)
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError as exc:
            raise ValueError("Fecha inválida o incompatible con el formato configurado") from exc
        # strptime es tolerante con algunos anchos; exigir representación exacta.
        if parsed.strftime(fmt) != text:
            raise ValueError("Fecha no canónica para el formato indicado")
        return parsed.date().isoformat()
    if kind == "boolean":
        text = str(value).lower()
        if text not in ("true", "false"):
            raise ValueError("Booleano esperado: true/false")
        return text
    raise ValueError(f"Tipo no admitido: {kind}")


def infer(value, opts):
    if empty(value):
        return "null"
    text = str(value)
    if re.fullmatch(r"[+-]?0\d+", text):
        return "codigo_texto"
    for kind in ("integer", "number", "boolean", "date"):
        try:
            convert(value, kind, opts)
            return kind
        except ValueError:
            pass
    return "string"


def fingerprint(path):
    path = Path(path).resolve()
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return {"ruta": str(path), "bytes": path.stat().st_size, "sha256": h.hexdigest()}


def unique_keys(pairs):
    """object_pairs_hook de json: una clave repetida (p. ej. la misma columna dos veces en un
    mapeo) es un error, no "gana la última" en silencio."""
    keys = [k for k, _ in pairs]
    repeated = sorted({k for k in keys if keys.count(k) > 1})
    if repeated:
        raise ValueError("Clave JSON repetida: " + ", ".join(repeated)[:120])
    return dict(pairs)


def load_config(path):
    with Path(path).open(encoding="utf-8") as stream:
        config = json.load(stream, object_pairs_hook=unique_keys)
    if not isinstance(config, dict):
        raise ValueError("La configuración debe ser un objeto JSON")
    return config


def _exclusion(values, columns, conditions):
    """Motivo si la fila cumple alguna condición explícita de exclusión (pies, totales); si no, None.
    Se mira la posición de la columna, así que también vale para filas más cortas que el encabezado."""
    for number, cond in enumerate(conditions, 1):
        position = columns.index(cond["columna"])
        value = values[position] if position < len(values) else None
        text = literal(value) or ""
        if "igual" in cond and text == cond["igual"]:
            return f"condición {number}: {cond['columna']} igual a «{cond['igual']}»"
        if "empieza_con" in cond and text.startswith(cond["empieza_con"]):
            return f"condición {number}: {cond['columna']} empieza con «{cond['empieza_con']}»"
        if cond.get("vacia") is True and empty(value):
            return f"condición {number}: {cond['columna']} vacía"
    return None


def _consume(header, records, source, sheet, limit, xlsx=False, header_row=1, conditions=()):
    table = Table([], [], str(source), sheet)
    if header is None or not header:
        table.issues.append(issue("archivo_vacio", source=str(source)))
        return table
    columns = [literal(v) if v is not None else "" for v in header]
    if any(empty(c) for c in columns) or len(set(columns)) != len(columns):
        table.complete = False
        table.issues.append(issue("encabezado_vacio_o_duplicado", row=header_row, source=str(source)))
        return table
    table.columns = columns
    missing = sorted({c["columna"] for c in conditions} - set(columns))
    if missing:
        raise ValueError("excluir_filas: columnas inexistentes en el encabezado: " + ", ".join(missing)[:120])
    if limit == 0:  # solo encabezado (vista previa de recetas): no se toca ninguna fila de datos
        table.complete = False
        return table
    for rowno, values in enumerate(records, header_row + 1):  # número de fila real del archivo
        if limit is not None and table.scanned >= limit:
            table.complete = False
            break
        table.scanned += 1
        if xlsx:
            while len(values) > len(columns) and values[-1] is None:
                values.pop()
            if len(values) < len(columns):
                values += [None] * (len(columns) - len(values))
        reason = _exclusion(values, columns, conditions) if conditions else None
        if reason:
            table.excluded.append((rowno, reason, [literal(v) for v in values]))
            continue
        if len(values) != len(columns):
            table.issues.append(issue("ancho_incorrecto", rowno, source=str(source),
                                      detail=f"esperado={len(columns)}, recibido={len(values)}"))
            continue
        table.rows.append(dict(zip(columns, [literal(v) for v in values], strict=True)))
        table.row_numbers.append(rowno)
    if not table.rows and not table.issues:
        table.warnings.append("sin_filas_de_datos")
    return table


def sheet_names(path):
    from openpyxl import load_workbook
    with Path(path).open("rb") as stream:
        book = load_workbook(stream, read_only=True, data_only=False, keep_links=False)
        try:
            return book.sheetnames
        finally:
            book.close()


def read_table(path, opts=None, limit=None):
    opts = opts or Options()
    path = Path(path).resolve()
    suffix = path.suffix.lower()
    if suffix == ".csv":
        if opts.sheet:
            raise ValueError("--sheet solo se aplica a libros Excel")
        with path.open(encoding=opts.encoding, newline="") as stream:
            reader = csv.reader(stream, delimiter=opts.delimiter, strict=True)
            for _ in range(opts.header_row - 1):  # títulos u otras filas antes del encabezado
                next(reader, None)
            table = _consume(next(reader, None), reader, path, None, limit, header_row=opts.header_row,
                             conditions=opts.exclude_rows)
        # Una sola columna cuyo encabezado contiene otro separador habitual: casi siempre
        # falta --delimiter. Se avisa (código 1) sin adivinar ni releer el archivo.
        if len(table.columns) == 1 and any(d in table.columns[0] for d in ";,\t|" if d != opts.delimiter):
            table.warnings.append("posible_delimitador_incorrecto")
        return table
    if suffix == ".json":
        if opts.header_row != 1 or opts.exclude_rows:
            raise ValueError("fila_encabezado y excluir_filas solo se aplican a CSV y XLSX")
        with path.open(encoding=opts.encoding) as stream:
            data = json.load(stream)
        if not isinstance(data, dict) or set(data) != {"columns", "rows"}:
            raise ValueError("Tabla JSON: objeto con columns y rows; use los archivos del kit")
        cols, rows = data["columns"], data["rows"]
        if not isinstance(cols, list) or not all(isinstance(c, str) for c in cols):
            raise ValueError("columns debe ser lista de textos")
        if not isinstance(rows, list) or not all(isinstance(r, dict) and set(r) == set(cols) for r in rows):
            raise ValueError("rows debe contener objetos con exactamente las columnas declaradas")
        if any(isinstance(v, (dict, list)) for r in rows for v in r.values()):
            raise ValueError("Las celdas JSON deben ser escalares")
        return _consume(cols, ([r[c] for c in cols] for r in rows), path, None, limit)
    if suffix not in (".xlsx", ".xlsm"):
        raise ValueError("Formato admitido: CSV, XLSX, XLSM (lectura) o tabla JSON del kit")
    from openpyxl import load_workbook
    with path.open("rb") as stream:
        book = load_workbook(stream, read_only=True, data_only=False, keep_links=False)
        try:
            if opts.sheet is None and len(book.sheetnames) != 1:
                raise ValueError("Libro con varias hojas: indique --sheet")
            name = opts.sheet or book.sheetnames[0]
            if name not in book.sheetnames:
                raise ValueError(f"Hoja inexistente: {name}")
            ws = book[name]
            ws.reset_dimensions()
            iterator = ws.iter_rows()
            for _ in range(opts.header_row - 1):
                next(iterator, None)
            header_cells = next(iterator, None)
            header = [cell.value for cell in header_cells] if header_cells else None
            if header:
                while header and header[-1] is None:
                    header.pop()
            warning_set = set()

            def records():
                for cells in iterator:
                    for cell in cells:
                        if cell.data_type == "f":
                            warning_set.add("formulas_leidas_como_texto_no_evaluadas")
                        if cell.data_type == "e":
                            warning_set.add("celdas_con_error_excel")
                        if cell.data_type == "n" and cell.value is not None and re.fullmatch(r"0{2,}", cell.number_format):
                            warning_set.add("codigos_numericos_con_formato_de_ceros_no_recuperado")
                    yield [cell.value for cell in cells]

            table = _consume(header, records(), path, name, limit, xlsx=True, header_row=opts.header_row,
                             conditions=opts.exclude_rows)
            table.warnings = sorted(set(table.warnings) | warning_set)
            if suffix == ".xlsm":
                table.warnings.append("macros_no_ejecutadas_ni_conservadas")
            return table
        finally:
            book.close()


def json_write(path, value):
    path = inside(path)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def atomic_json(path, value):
    """Reemplazo atómico de un archivo de estado: temporal en la misma carpeta y os.replace.
    Quien lee ve el contenido anterior completo o el nuevo completo, nunca uno a medias."""
    path = inside(path)
    temp = inside(path.with_name("." + path.name + "." + uuid4().hex[:8] + ".tmp"))
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def table_json(path, table):
    """Una fila por línea: JSON válido, compacto y escrito con el codificador rápido."""
    with inside(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write('{"columns": ' + json.dumps(table.columns, ensure_ascii=False) + ',\n"rows": [')
        separator = "\n"
        for row in table.rows:
            stream.write(separator + json.dumps(public_row(row), ensure_ascii=False, allow_nan=False))
            separator = ",\n"
        stream.write("\n]}\n")


def csv_write(path, table, delimiter=",", safe=False):
    """CSV fiel por defecto; neutralización opcional y explícita de fórmulas."""
    protected = 0

    def protect(values):
        nonlocal protected
        output = []
        for value in values:
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                value = "'" + value
                protected += 1
            output.append(value)
        return output

    with inside(path).open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter)
        writer.writerow(protect(table.columns) if safe else table.columns)
        columns = table.columns
        if safe:
            writer.writerows(protect([r.get(c) for c in columns]) for r in table.rows)
        else:
            writer.writerows([r.get(c) for c in columns] for r in table.rows)
    return protected


def excel_write(path, tables):
    """Libro nuevo en modo de solo escritura: memoria acotada y sin fórmulas activas."""
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    book = Workbook(write_only=True)
    font, fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="244B62")
    try:
        for name, table in tables.items():
            if len(table.rows) > 1048575 or len(table.columns) > 16384:
                raise ValueError("Tabla excede los límites de filas/columnas XLSX")
            ws = book.create_sheet(name)
            ws.freeze_panes = "A2"
            columns = table.columns
            if not columns:
                continue
            ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(table.rows) + 1}"
            for i, col in enumerate(columns, 1):
                width = max([len(col)] + [len(str(r.get(col) or "")) for r in table.rows[:100]])
                ws.column_dimensions[get_column_letter(i)].width = min(48, max(12, width + 2))

            def cell(value, header=False, ws=ws):
                text = literal(value)
                if text is None:
                    return None
                if len(text) > 32767:
                    raise ValueError("Celda excede 32767 caracteres: se rechaza para evitar truncamiento")
                if not header and text[:1] not in ("=", "#"):
                    return text  # openpyxl lo guarda como texto; no adivina números ni fechas
                forced = WriteOnlyCell(ws, value=text)
                forced.data_type = "s"  # conservar códigos y no activar fórmulas ni errores
                if header:
                    forced.font, forced.fill = font, fill
                return forced

            ws.append([cell(c, True) for c in columns])
            for row in table.rows:
                ws.append([cell(row.get(c)) for c in columns])
        with inside(path).open("xb") as stream:
            book.save(stream)
    except BaseException:
        # Cerrar y borrar los temporales de cada hoja; si no, quedan generadores abiertos.
        for ws in book.worksheets:
            with contextlib.suppress(Exception):
                ws.close()
                ws._writer.cleanup()
        raise
    book.close()

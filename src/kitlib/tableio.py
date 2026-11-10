"""Lectura sin inferencias destructivas y escritura exclusiva de tablas."""
import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from kitlib.runtime import inside


@dataclass
class Options:
    delimiter: str = ","
    encoding: str = "utf-8-sig"
    decimal: str = "."
    date_format: str | None = None
    sheet: str | None = None


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


def number(value, decimal="."):
    text = str(value).strip()
    pattern = r"[+-]?(?:\d+(?:" + re.escape(decimal) + r"\d+)?|" + re.escape(decimal) + r"\d+)"
    if not re.fullmatch(pattern, text):
        raise ValueError("Número inválido; no se admiten separadores de miles ni exponentes.")
    try:
        return Decimal(text.replace(decimal, "."))
    except InvalidOperation as exc:
        raise ValueError("Número inválido") from exc


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


def load_config(path):
    with Path(path).open(encoding="utf-8") as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise ValueError("La configuración debe ser un objeto JSON")
    return config


def _consume(header, records, source, sheet, limit, xlsx=False):
    table = Table([], [], str(source), sheet)
    if header is None or not header:
        table.issues.append(issue("archivo_vacio", source=str(source)))
        return table
    columns = [literal(v) if v is not None else "" for v in header]
    if any(empty(c) for c in columns) or len(set(columns)) != len(columns):
        table.complete = False
        table.issues.append(issue("encabezado_vacio_o_duplicado", row=1, source=str(source)))
        return table
    table.columns = columns
    for rowno, values in enumerate(records, 2):
        if limit is not None and table.scanned >= limit:
            table.complete = False
            break
        table.scanned += 1
        if xlsx:
            while len(values) > len(columns) and values[-1] is None:
                values.pop()
            if len(values) < len(columns):
                values += [None] * (len(columns) - len(values))
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
            return _consume(next(reader, None), reader, path, None, limit)
    if suffix == ".json":
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

            table = _consume(header, records(), path, name, limit, xlsx=True)
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


def table_json(path, table):
    json_write(path, {"columns": table.columns, "rows": table.rows})


def csv_write(path, table, delimiter=",", safe=False):
    """CSV fiel por defecto; neutralización opcional y explícita de fórmulas."""
    protected = 0
    with inside(path).open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter)
        for values in [table.columns] + [[r.get(c) for c in table.columns] for r in table.rows]:
            output = []
            for value in values:
                if safe and isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    value = "'" + value
                    protected += 1
                output.append(value)
            writer.writerow(output)
    return protected


def excel_write(path, tables):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    book = Workbook()
    book.remove(book.active)
    for name, table in tables.items():
        if len(table.rows) > 1048575 or len(table.columns) > 16384:
            raise ValueError("Tabla excede los límites de filas/columnas XLSX")
        ws = book.create_sheet(name)
        ws.freeze_panes = "A2"
        for rowno, values in enumerate([table.columns] + [[r.get(c) for c in table.columns] for r in table.rows], 1):
            for colno, value in enumerate(values, 1):
                text = literal(value)
                if text is not None and len(text) > 32767:
                    raise ValueError("Celda excede 32767 caracteres: se rechaza para evitar truncamiento")
                cell = ws.cell(rowno, colno, text)
                if text is not None:
                    cell.data_type = "s"  # conservar códigos y no activar fórmulas
                if rowno == 1:
                    cell.font = Font(bold=True, color="FFFFFF")
                    cell.fill = PatternFill("solid", fgColor="244B62")
        if table.columns:
            ws.auto_filter.ref = ws.dimensions
            for i, col in enumerate(table.columns, 1):
                width = max([len(col)] + [len(str(r.get(col) or "")) for r in table.rows[:100]])
                ws.column_dimensions[get_column_letter(i)].width = min(48, max(12, width + 2))
    with inside(path).open("xb") as stream:
        book.save(stream)
    book.close()

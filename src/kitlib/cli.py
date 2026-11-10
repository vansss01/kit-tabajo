import argparse
import fnmatch
import json
import re
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from kitlib import __version__
from kitlib.operations import compare, inspect_table, transform, validate
from kitlib.runtime import ROOT, inside
from kitlib.tableio import (Options, Table, csv_write, excel_write, fingerprint, issue,
                         json_write, load_config, read_table, sheet_names, table_json)

ISSUE_COLUMNS = ["codigo", "fila", "columna", "origen", "detalle"]


def parser():
    p = argparse.ArgumentParser(description="Kit local de tablas. Sin IA ni servicios externos.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    for name, helptext in [
        ("inspeccionar", "Estadísticas sin modificar datos"),
        ("comparar", "Altas, bajas y cambios por clave"),
        ("consolidar", "Unir tablas compatibles con procedencia"),
        ("validar", "Validar reglas JSON sin corregir"),
        ("transformar", "Aplicar un plan JSON limitado"),
        ("exportar", "Crear resultados CSV, JSON y Excel organizado")]:
        cmd = sub.add_parser(name, help=helptext, description=helptext)
        cmd.add_argument("input", type=Path, help="Archivo de entrada; carpeta para consolidar")
        cmd.add_argument("--delimiter", default=",", help="Separador CSV explícito (predeterminado: coma; TAB admite tabulación)")
        cmd.add_argument("--encoding", default="utf-8-sig", help="Codificación de entrada CSV/JSON")
        cmd.add_argument("--decimal", choices=[".", ","], default=".", help="Separador decimal para interpretar, nunca miles")
        cmd.add_argument("--date-format", help="Formato strptime explícito; predeterminado YYYY-MM-DD")
        cmd.add_argument("--sheet", help="Nombre exacto de hoja Excel")
        cmd.add_argument("--output", type=Path, default=ROOT / "results", help="Carpeta de resultados dentro del proyecto")
        cmd.add_argument("--run-name", help="Nombre exclusivo de ejecución; falla si ya existe")
        cmd.add_argument("--json", action="store_true", help="Resumen compacto JSON en stdout")
        cmd.add_argument("--verbose", action="store_true", help="Añadir detalle acotado (hasta 10 incidencias)")
        if name == "inspeccionar":
            cmd.add_argument("--sample", type=int, default=3, help="Filas de muestra en informe (0–20)")
            cmd.add_argument("--limit", type=int, help="Analizar solo las primeras N filas; sin estimar total")
        if name == "comparar":
            cmd.add_argument("after", type=Path, help="Tabla posterior")
            cmd.add_argument("--key", nargs="+", required=True, help="Una o más columnas clave")
            cmd.add_argument("--after-sheet", help="Hoja de la tabla posterior; predeterminado --sheet")
        if name == "consolidar":
            cmd.add_argument("--glob", default="*.csv", help="Patrón de archivos, p. ej. *.xlsx")
            cmd.add_argument("--recursive", action="store_true")
            cmd.add_argument("--exclude", action="append", default=[], help="Patrón relativo adicional a excluir")
        if name in ("validar", "exportar"):
            cmd.add_argument("--rules", type=Path, required=name == "validar", help="Reglas JSON de validación")
        if name == "transformar":
            cmd.add_argument("--plan", type=Path, required=True, help="Plan JSON declarativo")
        if name == "exportar":
            cmd.add_argument("--format", choices=["all", "xlsx", "csv", "json"], default="all")
            cmd.add_argument("--safe-csv", action="store_true", help="Añadir apóstrofo a textos que Excel podría ejecutar como fórmula")
    return p


def candidates(args):
    folder = args.input.resolve()
    if not folder.is_dir():
        raise ValueError("consolidar requiere una carpeta")
    excluded_dirs = {".venv", ".venv-win", ".cache", ".runtime", ".git", "tmp", "logs", "vendor"}
    paths, excluded = [], []
    for path in sorted(folder.rglob(args.glob) if args.recursive else folder.glob(args.glob)):
        if not path.is_file():
            continue
        relative = path.relative_to(folder)
        resolved = path.resolve()
        marked = any((parent / ".kit-output").exists() for parent in [resolved.parent, *resolved.parents])
        skip = (resolved.is_relative_to(args.output.resolve()) or resolved.is_relative_to(ROOT / "results")
                or bool(set(relative.parts) & excluded_dirs) or marked
                or any(fnmatch.fnmatch(relative.as_posix(), pat) for pat in args.exclude))
        if skip:
            excluded.append(str(path))
        else:
            paths.append(resolved)
    return sorted(set(paths)), excluded


def consolidate(paths, opts):
    columns = None
    rows, issues, accepted, rejected = [], [], [], []
    warnings: list[dict] = []
    scanned = 0
    for path in paths:
        try:
            table = read_table(path, opts)
        except Exception as exc:
            issues.append(issue("archivo_ilegible", source=str(path), detail=type(exc).__name__))
            rejected.append(str(path))
            continue
        scanned += table.scanned
        warnings.extend({"origen": str(path), "codigo": w} for w in table.warnings)
        if table.issues or not table.columns or "__archivo_origen" in table.columns or "__fila_origen" in table.columns:
            issues.extend(table.issues or [issue("columna_procedencia_reservada", source=str(path))])
            rejected.append(str(path))
            continue
        if columns is None:
            columns = table.columns
        if set(columns) != set(table.columns):
            issues.append(issue("columnas_incompatibles", source=str(path), detail=json.dumps({
                "faltantes": sorted(set(columns) - set(table.columns)),
                "adicionales": sorted(set(table.columns) - set(columns))}, ensure_ascii=False)))
            rejected.append(str(path))
            continue
        accepted.append(str(path))
        for rowno, row in zip(table.row_numbers, table.rows, strict=True):
            rows.append({**row, "__archivo_origen": str(path), "__fila_origen": str(rowno)})
    if not paths:
        issues.append(issue("sin_archivos_compatibles"))
    output = Table((columns or []) + ["__archivo_origen", "__fila_origen"], rows)
    return {"validos": output}, issues, warnings, {"aceptados": accepted, "rechazados": rejected,
        "filas_salida": len(rows), "filas_analizadas": scanned}


def bounded(value):
    if isinstance(value, dict):
        result = {str(k)[:100]: bounded(v) for k, v in list(value.items())[:20]}
        if len(value) > 20:
            result["_omitidos"] = len(value) - 20
        return result
    if isinstance(value, list):
        return [bounded(v) for v in value[:10]]
    if isinstance(value, str):
        return value[:200] + ("…" if len(value) > 200 else "")
    return value


def emit(summary, args, detail=None):
    detail = bounded(detail)
    if args.json:
        if args.verbose and detail is not None:
            summary["detalle_acotado"] = detail
        print(json.dumps(summary, ensure_ascii=False, allow_nan=False))
    else:
        print(f"{summary['estado']} | filas={summary['filas_procesadas']} | "
              f"incidencias={summary['incidencias']} | advertencias={summary['advertencias']}")
        if summary.get("ruta_resultados"):
            print("Resultados: " + summary["ruta_resultados"])
        if summary.get("error"):
            print(summary["error"])
        if args.verbose and detail is not None:
            print(json.dumps(detail, ensure_ascii=False, indent=2))


def execute(args):
    args.output = inside(args.output)
    args.delimiter = "\t" if args.delimiter == "TAB" else args.delimiter
    if len(args.delimiter) != 1 or args.delimiter in '\r\n"':
        raise ValueError("--delimiter requiere un carácter válido")
    opts = Options(args.delimiter, args.encoding, args.decimal, args.date_format, args.sheet)
    if args.command == "inspeccionar" and (not 0 <= args.sample <= 20 or (args.limit is not None and args.limit < 1)):
        raise ValueError("--sample debe estar entre 0 y 20; --limit debe ser positivo")
    run_name = args.run_name or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + args.command + "-" + uuid4().hex[:10]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_name):
        raise ValueError("--run-name admite letras ASCII, dígitos, guion y guion bajo (1–100)")
    args.output.mkdir(parents=True, exist_ok=True)
    run = inside(args.output / run_name)
    run.mkdir(exist_ok=False)
    (run / ".kit-output").touch(exist_ok=False)
    excluded = []
    paths = [args.input.resolve()]
    if args.command == "consolidar":
        paths, excluded = candidates(args)
    elif args.command == "comparar":
        paths.append(args.after.resolve())
    config_paths = [getattr(args, name) for name in ("rules", "plan") if getattr(args, name, None)]
    try:
        sources = [fingerprint(p) for p in paths]
        configs = [fingerprint(p) for p in config_paths]
        tables, issues, warnings, details = {}, [], [], {}
        processed = 0
        if args.command == "consolidar":
            tables, issues, warnings, details = consolidate(paths, opts)
            details["excluidos"] = excluded
            processed = details["filas_analizadas"]
        elif args.command == "inspeccionar":
            names = sheet_names(args.input) if args.input.suffix.lower() in (".xlsx", ".xlsm") else [None]
            details["hojas_disponibles"] = names
            details["analisis"] = []
            for sheet in ([args.sheet] if args.sheet else names):
                table = read_table(args.input, replace(opts, sheet=sheet), args.limit)
                details["analisis"].append(inspect_table(table, opts, args.sample))
                issues.extend(table.issues)
                warnings.extend({"origen": table.source, "hoja": sheet, "codigo": w} for w in table.warnings)
                processed += table.scanned
        else:
            table = read_table(args.input, opts)
            processed = table.scanned
            warnings.extend({"origen": table.source, "codigo": w} for w in table.warnings)
            if args.command == "comparar":
                after = read_table(args.after, replace(opts, sheet=args.after_sheet or opts.sheet))
                processed += after.scanned
                warnings.extend({"origen": after.source, "codigo": w} for w in after.warnings)
                tables, issues, details = compare(table, after, args.key)
            elif args.command in ("validar", "exportar"):
                if args.rules:
                    tables, issues, details = validate(table, load_config(args.rules), opts)
                else:
                    tables = {"validos": table, "invalidos": Table(table.columns, [])}
                    issues = table.issues
                    details = {"validacion_semantica": "no_solicitada", "filas_salida": len(table.rows)}
            else:
                tables, issues, details = transform(table, load_config(args.plan), opts)
        if sources != [fingerprint(p) for p in paths] or configs != [fingerprint(p) for p in config_paths]:
            raise ValueError("Una entrada cambió durante la ejecución; resultados descartados")
        code = 1 if issues or warnings else 0
        summary = {"estado": "incidencias" if code else "ok", "codigo_salida": code,
                   "comando": args.command, "filas_procesadas": processed,
                   "incidencias": len(issues), "advertencias": len(warnings),
                   "ruta_resultados": str(run)}
        report = {**summary, "detalle": details, "incidencias_detalle": issues, "advertencias_detalle": warnings}
        audit = {"version_kit": __version__, "python": sys.version.split()[0],
                 "fecha_utc": datetime.now(timezone.utc).isoformat(),
                 "parametros": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                 "fuentes": sources, "configuraciones": configs,
                 "resumen": summary, "originales_sha256_sin_cambios": True}
        issue_table = Table(ISSUE_COLUMNS, issues)
        summary_table = Table(["parametro", "valor"], [{"parametro": k, "valor": str(v)} for k, v in summary.items()])
        export_tables = {**tables, "incidencias": issue_table, "resumen": summary_table}
        formats = ["json", "csv"]
        if args.command == "exportar":
            formats = ["json", "csv", "xlsx"] if args.format == "all" else [args.format]
        protected = 0
        for name, output in export_tables.items():
            if "json" in formats:
                table_json(run / (name + ".json"), output)
            if "csv" in formats:
                protected += csv_write(run / (name + ".csv"), output, args.delimiter, getattr(args, "safe_csv", False))
        if "xlsx" in formats:
            excel_write(run / "resultado.xlsx", export_tables)
        report["celdas_csv_neutralizadas"] = protected
        report["archivos"] = sorted(p.name for p in run.iterdir() if not p.name.startswith(".")) + ["report.json", "audit.json"]
        json_write(run / "report.json", report)
        json_write(run / "audit.json", audit)
        log = inside(ROOT / "logs" / (run_name + "-" + uuid4().hex[:8] + ".json"))
        json_write(log, audit)
        detail = {"incidencias": issues[:10], "advertencias": warnings[:10]}
        if args.command == "inspeccionar":
            detail["analisis"] = details["analisis"][:5]
        emit(summary, args, detail)
        return code
    except Exception as exc:
        args.failed_results = run
        json_write(run / "FAILED.json", {"estado": "error", "tipo": type(exc).__name__,
                   "nota": "Ejecución incompleta; no utilizar resultados parciales."})
        raise


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return execute(args)
    except Exception as exc:
        # No volcar valores de celdas, configuraciones ni traceback por terminal.
        message = f"{type(exc).__name__}: no se completó la operación. Revise rutas, opciones y esquema de configuración."
        if type(exc) is ValueError:
            message = str(exc)[:240]
        if isinstance(exc, FileExistsError):
            message = "La salida ya existe. Use otro --run-name; no se sobrescribió."
        emit({"estado": "error", "codigo_salida": 2, "filas_procesadas": 0,
              "incidencias": 0, "advertencias": 0, "error": message,
              "ruta_resultados": str(args.failed_results) if hasattr(args, "failed_results") else None}, args)
        return 2

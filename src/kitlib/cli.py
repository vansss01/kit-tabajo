import argparse
import fnmatch
import functools
import json
import re
import shutil
import sys
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from kitlib import __version__, bitacora, contrato, receta_cli
from kitlib.operations import (DETECTOR_MAX_ROWS, compare, decimal_hint, inspect_table, merge_tables, query, query_warnings,
                               transform, validate)
from kitlib.receta_modelo import error
from kitlib.runtime import ROOT, KitError, error_info, inside, public_message
from kitlib.tableio import (Options, Table, csv_write, excel_write, fingerprint,
                         json_write, load_config, read_table, sheet_names, table_json)

ISSUE_COLUMNS = ["codigo", "fila", "columna", "origen", "detalle"]


class ErrorDeArgumentos(Exception):
    """Error de la línea de comandos (argparse) cuando hay --json: se convierte en el objeto de errores del kit."""

    def __init__(self, message, prog):
        super().__init__(message)
        self.prog = prog


class KitParser(argparse.ArgumentParser):
    """ArgumentParser que, con `estructurado`, lanza ErrorDeArgumentos en vez de imprimir el uso y salir.
    Sin `estructurado` se comporta exactamente como argparse (uso por stderr, código 2)."""

    def __init__(self, *args, estructurado=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.estructurado = estructurado

    def add_subparsers(self, **kwargs):
        kwargs.setdefault("parser_class", functools.partial(KitParser, estructurado=self.estructurado))
        return super().add_subparsers(**kwargs)

    def error(self, message):
        if self.estructurado:
            raise ErrorDeArgumentos(message, self.prog)
        super().error(message)


_DETALLES = [  # mensajes de argparse → castellano; si no coincide ninguno se conserva el texto original
    (re.compile(r"invalid int value: '(.*)'"), "se esperaba un entero, no '{0}'"),
    (re.compile(r"invalid float value: '(.*)'"), "se esperaba un número, no '{0}'"),
    (re.compile(r"invalid choice: '?(.*?)'? \(choose from (.*)\)"), "'{0}' no está entre: {1}"),
    (re.compile(r"expected one argument"), "falta su valor"),
    (re.compile(r"expected at least one argument"), "falta al menos un valor"),
    (re.compile(r"not allowed with argument (.*)"), "no se puede combinar con {0}"),
]


def argument_error(exc):
    """(código, campo, mensaje, sugerencia) para un error de argparse. Los códigos están en codigos.ERRORES."""
    message, prog = str(exc), exc.prog
    ayuda = f"Vea {prog} --help"
    found = re.fullmatch(r"the following arguments are required: (.+)", message)
    if found:
        fields = found.group(1).split(", ")
        return ("argumento_ausente", fields[0], "Falta el argumento obligatorio " + " y ".join(fields),
                f"Añada {fields[0]}; {ayuda.lower()[0] + ayuda[1:]}")
    found = re.fullmatch(r"argument command: invalid choice: '?(.*?)'? \(choose from (.*)\)", message)
    if found:
        commands = found.group(2).replace("'", "")
        return ("comando_desconocido", "comando", f"Comando desconocido: {found.group(1)}",
                f"Comandos: {commands}. ./kit catalogo los describe")
    found = re.fullmatch(r"argument (\S+): (.+)", message, re.DOTALL)
    if found:
        field, detail = found.group(1).split("/")[0], found.group(2)
        for pattern, text in _DETALLES:
            match = pattern.fullmatch(detail)
            if match:
                detail = text.format(*match.groups())
                break
        return "argumento_invalido", field, f"Valor no válido para {field}: {detail}", ayuda
    found = re.fullmatch(r"unrecognized arguments: (.+)", message)
    if found:
        field = found.group(1).split()[0]
        return ("argumento_desconocido", field, f"Argumento no reconocido: {found.group(1)}",
                f"{ayuda}; las opciones van después del comando y ./kit catalogo las lista")
    return "argumento_invalido", None, message[:240], ayuda


def parser(estructurado=False):
    p = KitParser(description="Kit local de tablas. Sin IA ni servicios externos.", estructurado=estructurado)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    for name, helptext in [
        ("inspeccionar", "Estadísticas sin modificar datos"),
        ("comparar", "Altas, bajas y cambios por clave"),
        ("consolidar", "Unir tablas compatibles con procedencia"),
        ("validar", "Validar reglas JSON sin corregir"),
        ("transformar", "Aplicar un plan JSON limitado"),
        ("exportar", "Crear resultados CSV, JSON y Excel organizado"),
        ("consultar", "Consultar una o varias tablas con SQL (solo SELECT)")]:
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
        cmd.add_argument("--ocultar-valores", action="store_true", help="No mostrar valores de celdas en terminal ni en report.json (consultar: sin filas; inspeccionar: sin muestra). Los archivos de datos no cambian")
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
        if name == "consultar":
            cmd.add_argument("--sql", required=True, help="Consulta SELECT; la tabla de entrada se llama t")
            cmd.add_argument("--name", default="t", help="Nombre SQL de la tabla de entrada (t)")
            cmd.add_argument("--tabla", action="append", default=[], metavar="NOMBRE=ARCHIVO",
                             help="Tabla adicional para JOIN; repetible")
            cmd.add_argument("--numeric", nargs="+", default=[], metavar="COLUMNA",
                             help="Columnas a cargar como número según --decimal en todas las tablas que las "
                                  "tengan; el resto es texto. Necesario para sumar, comparar u ordenar medidas")
            cmd.add_argument("--tipo", action="append", default=[], metavar="TABLA.COLUMNA=TIPO",
                             help="Tipo explícito de una columna de una tabla: number o string; repetible")
            cmd.add_argument("--detector-texto-numerico", choices=["si", "no"], default="si",
                             help="Repetir la consulta con columnas de texto con decimales como número y avisar si "
                                  "el resultado cambia (heurístico; no valida el SQL)")
            cmd.add_argument("--detector-max-filas", type=int, default=DETECTOR_MAX_ROWS,
                             help=f"Filas totales máximas para el detector ({DETECTOR_MAX_ROWS}); por encima avisa "
                                  "detector_texto_numerico_omitido")
            cmd.add_argument("--show", type=int, default=20, help="Filas del resultado a mostrar en la terminal (0–100); 0 las oculta, los archivos no cambian")
        if name == "exportar":
            cmd.add_argument("--format", choices=["all", "xlsx", "csv", "json"], default="all")
            cmd.add_argument("--safe-csv", action="store_true", help="Añadir apóstrofo a textos que Excel podría ejecutar como fórmula")
    cmd = sub.add_parser("limpiar", help="Listar o borrar ejecuciones y registros antiguos",
                         description="Conserva las ejecuciones y registros más recientes. Sin --apply solo informa.")
    cmd.add_argument("--keep", type=int, default=20, help="Cantidad de ejecuciones y de registros a conservar")
    cmd.add_argument("--apply", action="store_true", help="Borrar de verdad; sin esta opción no se elimina nada")
    cmd.add_argument("--json", action="store_true", help="Resumen compacto JSON en stdout")
    cmd.set_defaults(verbose=False)
    bitacora.add_parser(sub)
    receta_cli.add_parser(sub)
    contrato.add_parsers(sub)
    contrato.add_results_parser(sub)
    # Interfaz visual local: solo se definen aquí sus argumentos; el módulo kitlib.interfaz se importa
    # únicamente al ejecutar el comando, así el núcleo del kit no depende de él.
    ui = sub.add_parser("interfaz", help="Abrir la interfaz visual local en el navegador (solo 127.0.0.1)",
                        description="Inicia un servidor HTTP local en 127.0.0.1 con un token de sesión y abre la "
                                    "página en el navegador. Termina con Ctrl+C. Manual: docs/tools/interfaz.md")
    ui.add_argument("--puerto", type=int, default=0, help="Puerto en 127.0.0.1 (predeterminado: uno libre)")
    ui.add_argument("--sin-abrir", action="store_true", help="No abrir el navegador; solo mostrar la URL")
    return p


def clean(keep, apply, results, logs):
    """Solo carpetas marcadas con .kit-output y registros de ejecución; nunca datos ni originales."""
    if keep < 0:
        raise KitError("--keep no puede ser negativo", "--keep")

    def recent(paths):
        return sorted(paths, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)

    results, logs = inside(results), inside(logs)
    runs = recent(p for p in results.iterdir() if p.is_dir() and not p.is_symlink()
                  and (p / ".kit-output").is_file()) if results.is_dir() else []
    records = recent(p for p in logs.iterdir() if p.is_file() and not p.is_symlink()
                     and re.fullmatch(r".+-[0-9a-f]{8}\.json", p.name)) if logs.is_dir() else []
    old_runs, old_records = runs[keep:], records[keep:]
    size = sum(f.stat().st_size for run in old_runs for f in run.rglob("*") if f.is_file() and not f.is_symlink())
    size += sum(p.stat().st_size for p in old_records)
    if apply:
        for run in old_runs:
            shutil.rmtree(inside(run))
        for record in old_records:
            inside(record).unlink()
    return {"estado": "ok", "codigo_salida": 0, "comando": "limpiar", "aplicado": apply,
            "ejecuciones_conservadas": len(runs) - len(old_runs), "ejecuciones_antiguas": len(old_runs),
            "registros_conservados": len(records) - len(old_records), "registros_antiguos": len(old_records),
            "bytes_antiguos": size}


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
    items: list[tuple[str, Table | None, str | None]] = []
    warnings: list[dict] = []
    scanned = 0
    for path in paths:
        try:
            table = read_table(path, opts)
        except Exception as exc:
            items.append((str(path), None, type(exc).__name__))
            continue
        scanned += table.scanned
        warnings.extend({"origen": str(path), "codigo": w} for w in table.warnings)
        items.append((str(path), table, None))
    output, issues, details = merge_tables(items)
    return {"validos": output}, issues, warnings, {**details, "filas_analizadas": scanned}


def sql_types(items):
    """--tipo TABLA.COLUMNA=number|string → {(tabla, columna): tipo}."""
    found: dict[tuple[str, str], str] = {}
    for item in items:
        target, sep, kind = item.rpartition("=")
        table, dot, column = target.partition(".")
        if not sep or not dot or not table or not column or kind not in ("number", "string") or (table, column) in found:
            raise KitError("--tipo requiere TABLA.COLUMNA=number o TABLA.COLUMNA=string, sin repetir", "--tipo",
                           "Ejemplo: --tipo t.horas=number --tipo flota.codigo=string")
        found[table, column] = kind
    return found


def delimiter_hint(header, current):
    """Opción sugerida a partir del encabezado; no se relee ni se adivina el contenido."""
    best = max((d for d in ";,\t|" if d != current), key=header.count)
    return "--delimiter " + ("TAB" if best == "\t" else "'" + best + "'")


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
        if summary.get("sugerencia"):
            print("Sugerencia: " + summary["sugerencia"])
        for key in ("incidencias_por_codigo", "advertencias_por_codigo", "conteos"):
            if summary.get(key):
                print(key + ": " + ", ".join(f"{k}={v}" for k, v in summary[key].items()))
        shown = summary.get("resultado")
        if shown and shown["filas"]:
            widths = [min(40, max(len(c), *(len(str(r[c] or "")) for r in shown["filas"]))) for c in shown["columnas"]]
            for values in [shown["columnas"], *([r[c] for c in shown["columnas"]] for r in shown["filas"])]:
                print("  ".join(str("" if v is None else v)[:w].ljust(w) for v, w in zip(values, widths, strict=True)).rstrip())
            if summary["conteos"]["filas_salida"] > len(shown["filas"]):
                print(f"… {summary['conteos']['filas_salida'] - len(shown['filas'])} filas más en validos.csv")
        for item in summary.get("tablas", []):
            print(f"{item['hoja'] or 'tabla'} ({item['filas']} filas, {item['alcance']}): " + ", ".join(item["columnas"]))
        if args.verbose and detail is not None:
            print(json.dumps(detail, ensure_ascii=False, indent=2))


def execute(args):
    args.output = inside(args.output)
    # --ocultar-valores: las únicas salidas de terminal/report.json con valores de celdas son estas dos.
    if args.ocultar_valores and args.command == "consultar":
        args.show = 0
    if args.ocultar_valores and args.command == "inspeccionar":
        args.sample = 0
    args.delimiter = "\t" if args.delimiter == "TAB" else args.delimiter
    if len(args.delimiter) != 1 or args.delimiter in '\r\n"':
        raise KitError("--delimiter requiere un carácter válido", "--delimiter")
    opts = Options(args.delimiter, args.encoding, args.decimal, args.date_format, args.sheet)
    extra_tables: list[tuple[str, Path]] = []
    if args.command == "consultar":
        if args.detector_max_filas < 1:
            raise KitError("--detector-max-filas debe ser 1 o más", "--detector-max-filas")
        if not 0 <= args.show <= 100:
            raise KitError("--show debe estar entre 0 y 100", "--show")
        for item in args.tabla:
            name, separator, location = item.partition("=")
            if not separator or not name or not location or name == args.name or name in dict(extra_tables):
                raise KitError("--tabla requiere NOMBRE=ARCHIVO con nombres distintos", "--tabla")
            extra_tables.append((name, Path(location)))
    if args.command == "inspeccionar" and (not 0 <= args.sample <= 20 or (args.limit is not None and args.limit < 1)):
        raise KitError("--sample debe estar entre 0 y 20; --limit debe ser positivo", "--sample")
    run_name = args.run_name or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + args.command + "-" + uuid4().hex[:10]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_name):
        raise KitError("--run-name admite letras ASCII, dígitos, guion y guion bajo (1–100)", "--run-name")
    if re.fullmatch(r"(?i)con|prn|aux|nul|com\d|lpt\d", run_name):
        raise KitError("--run-name no puede ser un nombre reservado de Windows", "--run-name")
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
    paths += [location.resolve() for _, location in extra_tables]
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
            if args.command == "consultar":
                loaded = {args.name: table}
                for name, location in extra_tables:
                    loaded[name] = read_table(location, opts)
                    processed += loaded[name].scanned
                    warnings.extend({"origen": loaded[name].source, "codigo": w} for w in loaded[name].warnings)
                tables, issues, details = query(loaded, args.sql, set(args.numeric), opts, None,
                                                sql_types(args.tipo), args.detector_texto_numerico == "si",
                                                args.detector_max_filas)
                warnings.extend(query_warnings(details, table.source, opts.decimal))
            elif args.command == "comparar":
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
                warnings.extend(details.pop("advertencias", []))
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
        if not args.output.is_relative_to(ROOT / "tmp"):  # ejecuciones temporales: audit.json basta
            json_write(inside(ROOT / "logs" / (run_name + "-" + uuid4().hex[:8] + ".json")), audit)
        detail = {"incidencias": issues[:10], "advertencias": warnings[:10]}
        # Extras solo para la terminal: evitan abrir report.json en el caso habitual.
        # Contienen códigos, conteos y nombres de columnas, sin valores de celdas. Única excepción:
        # `resultado` de consultar, que muestra filas salvo con --show 0.
        extras: dict = {}
        if issues:
            extras["incidencias_por_codigo"] = dict(Counter(i["codigo"] for i in issues).most_common(15))
        if warnings:
            extras["advertencias_por_codigo"] = dict(Counter(w["codigo"] for w in warnings).most_common(15))
        if args.command != "consolidar" and len(table.columns) == 1 and any(
                w["codigo"] == "posible_delimitador_incorrecto" for w in warnings):
            extras["sugerencia"] = delimiter_hint(table.columns[0], args.delimiter)
        hints = []
        if details.get("valores_con_otro_decimal"):  # consultar: NULL evitables con el otro --decimal
            hints.append(decimal_hint(opts.decimal, details["valores_con_otro_decimal"]))
        if details.get("columnas_sin_numeric"):
            hints.append("el resultado cambia si estas columnas se cargan como número; si son medidas, "
                         "repita con --numeric " + " ".join(c[:60] for c in details["columnas_sin_numeric"][:10]))
        if hints:
            extras["sugerencia"] = "; ".join(hints)
        if args.command == "inspeccionar":
            detail["analisis"] = details["analisis"][:5]
            extras["tablas"] = [{"hoja": a["hoja"], "filas": a["filas_analizadas"], "alcance": a["alcance"],
                                 "columnas": [c[:60] for c in list(a["columnas"])[:40]]}
                                for a in details["analisis"][:5]]
        else:
            extras["conteos"] = {k: len(v) if isinstance(v, list) else v for k, v in details.items()
                                 if isinstance(v, (int, str, list)) and k != "pasos"}
        if args.command == "consultar" and args.show:
            result = tables["validos"]
            extras["resultado"] = {"columnas": [c[:60] for c in result.columns[:30]],
                                   "filas": [{c[:60]: (v[:80] if isinstance(v, str) else v) for c, v in list(r.items())[:30]}
                                             for r in result.rows[:args.show]]}
        emit({**summary, **extras}, args, detail)
        return code
    except Exception as exc:
        args.failed_results = run
        json_write(run / "FAILED.json", {"estado": "error", "tipo": type(exc).__name__,
                   "nota": "Ejecución incompleta; no utilizar resultados parciales."})
        raise


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        # Con --json en la línea, un error de argumentos sale como el mismo objeto de errores que el resto
        # del kit (stdout, código 2). Sin --json, argparse imprime su uso por stderr, como siempre.
        args = parser(estructurado="--json" in argv).parse_args(argv)
    except ErrorDeArgumentos as exc:
        code, field, message, hint = argument_error(exc)
        print(json.dumps({"estado": "error", "codigo_salida": 2, "filas_procesadas": 0, "incidencias": 0,
                          "advertencias": 0, "error": message, "errores": [error(code, message, None, field, hint)],
                          "ruta_resultados": None}, ensure_ascii=False))
        return 2
    try:
        if args.command == "limpiar":
            result = clean(args.keep, args.apply, ROOT / "results", ROOT / "logs")
            if args.json:
                print(json.dumps(result, ensure_ascii=False))
            else:
                print(f"{'Eliminadas' if args.apply else 'Eliminables (use --apply)'}: "
                      f"{result['ejecuciones_antiguas']} ejecuciones y {result['registros_antiguos']} registros, "
                      f"{result['bytes_antiguos']} bytes. Conservadas: {result['ejecuciones_conservadas']} "
                      f"ejecuciones y {result['registros_conservados']} registros.")
            return 0
        if args.command == "bitacora":
            return bitacora.run(args)
        if args.command == "ejecutar":
            return receta_cli.run(args)
        if args.command in ("catalogo", "comprobar", "resultados"):
            return contrato.run(args, parser)
        if args.command == "interfaz":
            from kitlib.interfaz import servidor
            return servidor.run(args)
        return execute(args)
    except Exception as exc:
        # No volcar valores de celdas, configuraciones ni traceback por terminal.
        message = public_message(exc, getattr(args, "encoding", ""))
        if args.command in ("limpiar", "bitacora") and not args.json:
            print(message)
            return 2
        code, field, hint = error_info(exc)
        emit({"estado": "error", "codigo_salida": 2, "filas_procesadas": 0,
              "incidencias": 0, "advertencias": 0, "error": message,
              "errores": [error(code, message, None, field, hint)],  # solo visible con --json
              "ruta_resultados": str(args.failed_results) if hasattr(args, "failed_results") else None}, args)
        return 2

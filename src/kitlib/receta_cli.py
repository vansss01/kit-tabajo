"""Comando `ejecutar`: argumentos, salida en terminal y orquestación de validar, previsualizar
y ejecutar una receta."""
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from kitlib.runtime import ROOT, KitError, inside
from kitlib.receta_modelo import RecipeError
from kitlib.receta_validacion import cargar_receta
from kitlib.receta_vista import comprobar_columnas, vista_previa
from kitlib.recetas import _summary, ejecutar_receta


def add_parser(sub):
    cmd = sub.add_parser("ejecutar", help="Ejecutar una receta JSON de pasos del kit",
                         description="Ejecuta en orden los pasos de una receta. Sin --vista-previa crea una "
                                     "carpeta de ejecución con manifiesto.json.")
    cmd.add_argument("input", type=Path, help="Archivo de la entrada principal de la receta")
    cmd.add_argument("--receta", type=Path, required=True, help="Receta JSON (ver docs/tools/ejecutar.md)")
    cmd.add_argument("--entrada", action="append", default=[], metavar="NOMBRE=ARCHIVO",
                     help="Reemplaza el archivo de otra entrada de la receta; repetible")
    cmd.add_argument("--vista-previa", action="store_true",
                     help="Describir pasos, entradas, políticas y destinos sin leer datos ni crear resultados")
    cmd.add_argument("--output", type=Path, default=ROOT / "results", help="Carpeta de resultados dentro del proyecto")
    cmd.add_argument("--run-name", help="Nombre exclusivo de ejecución; falla si ya existe")
    cmd.add_argument("--json", action="store_true", help="Resumen compacto JSON en stdout")
    cmd.add_argument("--verbose", action="store_true", help="Añadir hasta 10 incidencias al resumen")
    cmd.add_argument("--ocultar-valores", action="store_true", help="No mostrar valores de celdas en terminal ni en report.json (consultar: sin filas; inspeccionar: sin muestra). Los archivos de datos no cambian")


# --------------------------------------------------------------------------- CLI

def _show(summary, args, issues=None):
    if args.json:
        if args.verbose and issues:
            summary["detalle_acotado"] = issues[:10]
        print(json.dumps(summary, ensure_ascii=False))
        return
    if summary["estado"] == "vista_previa":
        print("VISTA PREVIA (solo encabezados; filas no leídas ni validadas) | receta: " + summary["receta"])
        for e in summary["entradas"]:
            print(f"  entrada {e['nombre']}: {e['ruta']} (delimiter {e['delimiter']!r}, decimal {e['decimal']!r},"
                  f" incidencias={e['politica']['incidencias']}) | encabezado {e['encabezado']}"
                  + (f": {e['motivo']}" if e.get("motivo") else ""))
        for s in summary["pasos"]:
            print(f"  {s['numero']:>2} {s['nombre']} ({s['op']}) usa {json.dumps(s['usa'], ensure_ascii=False)}"
                  f" → {', '.join(s['produce']) or 'solo informe'} | incidencias={s['politica']['incidencias']}"
                  + (f", permite {', '.join(s['politica']['advertencias_permitidas'])}"
                     if s['politica']['advertencias_permitidas'] else "") + f" | columnas {s['columnas']}")
        for kind in ("errores", "avisos"):
            for err in summary[kind][:10]:
                print(f"  [{err['codigo']}] {err.get('paso') or err.get('campo')}: {err['mensaje']}")
        print(summary["destino"])
        return
    print(f"{summary['estado']} | pasos={sum(p['estado'].startswith('completado') for p in summary.get('pasos', []))}"
          f"/{len(summary.get('pasos', []))} | incidencias={summary.get('incidencias', 0)} | "
          f"advertencias={summary.get('advertencias', 0)}")
    if summary.get("ruta_resultados"):
        print("Resultados: " + summary["ruta_resultados"])
    if summary.get("error"):
        print(summary["error"])
    for p in summary.get("pasos", []):
        rows = ", ".join(f"{k}={v}" for k, v in p["filas"].items())
        print(f"  {p['nombre']} ({p['op']}): {p['estado']}" + (f" | {rows}" if rows else "")
              + (f" | incidencias={p['incidencias']}" if p["incidencias"] else "")
              + (f" | advertencias={p['advertencias']}" if p["advertencias"] else ""))
    for err in summary.get("errores", [])[:10]:
        where = " / ".join(str(x) for x in (err.get("paso"), err.get("campo")) if x)
        print(f"[{err['codigo']}] {where + ': ' if where else ''}{err['mensaje']}"
              + (f"\n    Sugerencia: {err['sugerencia']}" if err.get("sugerencia") else ""))
    for key in ("incidencias_por_codigo", "advertencias_por_codigo"):
        if summary.get(key):
            print(key + ": " + ", ".join(f"{k}={v}" for k, v in summary[key].items()))


def run(args):
    overrides = {}
    for item in args.entrada:
        name, sep, location = item.partition("=")
        if not sep or not name or not location or name in overrides:
            raise KitError("--entrada requiere NOMBRE=ARCHIVO, sin repetir nombres", "--entrada")
        overrides[name] = location
    try:
        if not args.receta.is_file():
            raise KitError("No existe la receta", "--receta", "Revise la ruta y las comillas",
                           codigo="archivo_no_encontrado")
        recipe = cargar_receta(args.receta, args.input, overrides)
    except RecipeError as exc:
        summary = {"estado": "error", "codigo_salida": 2, "comando": "ejecutar", "ruta_resultados": None,
                   "error": "Receta inválida: no se ejecutó nada", "errores": exc.errors[:20],
                   "total_errores": len(exc.errors)}
        _show(summary, args)
        return 2
    if args.vista_previa:
        preview = vista_previa(recipe)
        _show(preview, args)
        return preview["codigo_salida"]
    column_errors = comprobar_columnas(recipe)[2]
    if column_errors:
        _show({"estado": "error", "codigo_salida": 2, "comando": "ejecutar", "ruta_resultados": None,
               "error": "Columnas incompatibles con los encabezados: no se ejecutó nada",
               "errores": column_errors[:20], "total_errores": len(column_errors)}, args)
        return 2
    output = inside(args.output)
    run_name = args.run_name or (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-ejecutar-"
                                 + uuid4().hex[:10])
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_name) or re.fullmatch(r"(?i)con|prn|aux|nul|com\d|lpt\d", run_name):
        raise KitError("--run-name admite letras ASCII, dígitos, guion y guion bajo (1–100), sin nombres reservados", "--run-name")
    output.mkdir(parents=True, exist_ok=True)
    folder = inside(output / run_name)
    folder.mkdir(exist_ok=False)
    (folder / ".kit-output").touch(exist_ok=False)
    if args.ocultar_valores:  # inspeccionar es el único paso que puede poner muestras en un informe
        for step in recipe.pasos:
            if step.op == "inspeccionar":
                step.spec = {**step.spec, "sample": 0}
    code = ejecutar_receta(recipe, folder, args)
    manifest = json.loads((folder / "manifiesto.json").read_text(encoding="utf-8"))
    summary = {"estado": manifest["estado"], "codigo_salida": code, "comando": "ejecutar",
               "receta": recipe.nombre, "motivo": manifest["motivo"], "ruta_resultados": str(folder),
               "manifiesto": str(folder / "manifiesto.json")}
    if manifest["error"]:
        summary["errores"] = [manifest["error"]]
    issues = []
    for p in manifest["pasos"]:
        report = folder / p["carpeta"] / "report.json"
        if args.verbose and report.is_file():
            issues.extend(json.loads(report.read_text(encoding="utf-8"))["incidencias_detalle"])
    totals = _summary(manifest, folder, [], [], code, manifest["estado"])
    totals.update(incidencias=sum(p.get("incidencias", 0) for p in manifest["pasos"])
                  + sum(e.get("incidencias", 0) for e in manifest["entradas"].values()),
                  advertencias=sum(p.get("advertencias", 0) for p in manifest["pasos"])
                  + sum(e.get("advertencias", 0) for e in manifest["entradas"].values()))
    by_code: Counter = Counter()
    by_warning: Counter = Counter()
    for item in [*manifest["pasos"], *manifest["entradas"].values()]:
        by_code.update(item.get("incidencias_por_codigo", {}))
        by_warning.update(item.get("advertencias_por_codigo", {}))
    totals.update(incidencias_por_codigo=dict(by_code.most_common(15)),
                  advertencias_por_codigo=dict(by_warning.most_common(15)))
    _show({**totals, **summary}, args, issues)
    return code

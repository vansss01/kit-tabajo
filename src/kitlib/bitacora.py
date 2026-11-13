"""Bitácora de práctica: anotaciones diarias en un CSV local y borrador de informe."""
import csv
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from kitlib.runtime import ROOT, KitError, inside

COLUMNS = ["fecha", "registrado", "horas", "etiqueta", "texto"]
DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def add_parser(sub):
    cmd = sub.add_parser("bitacora", help="Anotar el trabajo diario y generar el borrador del informe",
                         description="Sin opciones de consulta, agrega una anotación. Los datos quedan en data/bitacora/.")
    cmd.add_argument("texto", nargs="?", help="Qué hiciste, entre comillas")
    cmd.add_argument("--horas", help="Horas dedicadas (p. ej. 2,5)")
    cmd.add_argument("--etiqueta", default="general", help="Tema corto para agrupar: datos, soporte, reunion…")
    cmd.add_argument("--fecha", help="Fecha YYYY-MM-DD; por defecto hoy")
    cmd.add_argument("--ver", nargs="?", const=10, type=int, metavar="N", help="Mostrar las últimas N anotaciones (10)")
    cmd.add_argument("--informe", action="store_true", help="Generar informe_practica.md agrupado por semana")
    cmd.add_argument("--desde", help="Informe: fecha inicial YYYY-MM-DD")
    cmd.add_argument("--hasta", help="Informe: fecha final YYYY-MM-DD")
    cmd.add_argument("--archivo", type=Path, default=ROOT / "data" / "bitacora" / "bitacora.csv",
                     help="Archivo de bitácora dentro del proyecto")
    cmd.add_argument("--json", action="store_true", help="Resumen compacto JSON en stdout")
    cmd.set_defaults(verbose=False)


def parse_day(text, name):
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} debe tener formato YYYY-MM-DD") from exc


def load(path):
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        if reader.fieldnames != COLUMNS:
            raise ValueError("La bitácora no tiene las columnas esperadas; no se modificó")
        return [row for row in reader if row["fecha"]]


def add(path, text, hours, tag, day):
    text = " ".join(str(text).split())
    if not text or len(text) > 1000:
        raise ValueError("El texto debe tener entre 1 y 1000 caracteres")
    tag = " ".join(str(tag).lower().split()) or "general"
    if len(tag) > 30 or ";" in tag:
        raise KitError("--etiqueta admite hasta 30 caracteres, sin punto y coma", "--etiqueta")
    amount = ""
    if hours is not None:
        try:
            value = Decimal(str(hours).strip().replace(",", "."))
        except InvalidOperation as exc:
            raise KitError("--horas debe ser un número, p. ej. 2,5", "--horas") from exc
        if not value.is_finite() or not 0 < value <= 24:
            raise KitError("--horas debe estar entre 0 y 24", "--horas")
        amount = format(value.normalize(), "f")
    load(path)  # valida el archivo existente antes de escribir
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        if new:
            writer.writerow(COLUMNS)
        writer.writerow([day.isoformat(), datetime.now().strftime("%Y-%m-%d %H:%M"), amount, tag, text])
    return {"estado": "ok", "codigo_salida": 0, "comando": "bitacora", "accion": "anotado",
            "fecha": day.isoformat(), "anotaciones": len(load(path)), "archivo": str(path)}


def total(rows):
    return sum((Decimal(r["horas"]) for r in rows if r["horas"]), Decimal(0))


def hours_text(value):
    return format(value.normalize(), "f") if value else "0"


def report(rows, since, until):
    rows = sorted((r for r in rows if (since is None or r["fecha"] >= since.isoformat())
                   and (until is None or r["fecha"] <= until.isoformat())), key=lambda r: (r["fecha"], r["registrado"]))
    if not rows:
        raise ValueError("No hay anotaciones en el período indicado")
    weeks = defaultdict(list)
    for row in rows:
        day = date.fromisoformat(row["fecha"])
        weeks[day - timedelta(days=day.weekday())].append(row)
    tags = defaultdict(list)
    for row in rows:
        tags[row["etiqueta"]].append(row)
    days = sorted({r["fecha"] for r in rows})
    lines = ["# Informe de práctica (borrador)", "",
             f"Período: {days[0]} a {days[-1]}. Días con registro: {len(days)}. "
             f"Anotaciones: {len(rows)}. Horas registradas: {hours_text(total(rows))}.", "",
             "Generado desde la bitácora. Revisa la redacción y completa las secciones finales.", "",
             "## Resumen por tema", "", "| Tema | Anotaciones | Horas |", "|---|---|---|"]
    for tag, items in sorted(tags.items(), key=lambda kv: (-total(kv[1]), -len(kv[1]), kv[0])):
        lines.append(f"| {tag} | {len(items)} | {hours_text(total(items))} |")
    lines += ["", "## Actividades por semana"]
    for number, (monday, items) in enumerate(sorted(weeks.items()), 1):
        lines += ["", f"### Semana {number} ({monday.isoformat()} a {(monday + timedelta(days=6)).isoformat()}) — "
                      f"{hours_text(total(items))} horas", ""]
        current = None
        for row in items:
            if row["fecha"] != current:
                current = row["fecha"]
                lines.append(f"- **{DAYS[date.fromisoformat(current).weekday()].capitalize()} {current}**")
            extra = f" ({row['horas']} h)" if row["horas"] else ""
            lines.append(f"  - [{row['etiqueta']}] {row['texto']}{extra}")
    lines += ["", "## Aprendizajes", "", "_Completar: qué aprendiste, técnico y no técnico._", "",
              "## Dificultades y cómo se resolvieron", "", "_Completar._", "",
              "## Conclusiones", "", "_Completar._", ""]
    summary = {"semanas": len(weeks), "dias": len(days), "anotaciones": len(rows),
               "horas": hours_text(total(rows)), "por_etiqueta": {t: len(i) for t, i in sorted(tags.items())}}
    return "\n".join(lines), summary


def run(args):
    path = inside(args.archivo)
    if args.texto is not None:
        if args.informe or args.ver is not None:
            raise ValueError("Use el texto solo, o --ver, o --informe")
        result = add(path, args.texto, args.horas, args.etiqueta,
                     parse_day(args.fecha, "--fecha") if args.fecha else date.today())
        human = f"Anotado el {result['fecha']}. Total: {result['anotaciones']} anotaciones."
    elif args.ver is not None:
        if not 1 <= args.ver <= 100:
            raise KitError("--ver admite de 1 a 100", "--ver")
        rows = load(path)[-args.ver:]
        result = {"estado": "ok", "codigo_salida": 0, "comando": "bitacora", "accion": "ver", "anotaciones": rows}
        human = "\n".join(f"{r['fecha']} [{r['etiqueta']}] {r['texto']}" + (f" ({r['horas']} h)" if r["horas"] else "")
                          for r in rows) or "La bitácora está vacía."
    elif args.informe:
        text, summary = report(load(path), parse_day(args.desde, "--desde") if args.desde else None,
                               parse_day(args.hasta, "--hasta") if args.hasta else None)
        name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-bitacora-" + uuid4().hex[:10]
        folder = inside(path.parent / "informes" / name) if path.parent != ROOT / "data" / "bitacora" \
            else inside(ROOT / "results" / name)
        folder.mkdir(parents=True, exist_ok=False)
        (folder / ".kit-output").touch()
        with (folder / "informe_practica.md").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        result = {"estado": "ok", "codigo_salida": 0, "comando": "bitacora", "accion": "informe",
                  **summary, "ruta_resultados": str(folder)}
        human = (f"Informe: {folder / 'informe_practica.md'}\n{summary['semanas']} semanas, {summary['dias']} días, "
                 f"{summary['anotaciones']} anotaciones, {summary['horas']} horas.")
    else:
        raise ValueError('Indique un texto entre comillas, --ver o --informe. Ejemplo: bitacora "Revisé planilla" --horas 2')
    print(json.dumps(result, ensure_ascii=False) if args.json else human)
    return 0

"""Mutaciones manuales: introduce a propósito un error real por vez en una copia del kit y
comprueba que alguna prueba lo detecta. Uso: `python -B scripts/mutaciones.py [texto]`
(texto filtra por nombre). Código 0: todas detectadas; 1: alguna no; 2: un patrón ya no existe.

Para añadir una: (nombre, archivo, texto original exacto y único, texto que lo rompe, pruebas).
No modifica el proyecto: trabaja en una copia temporal dentro de tmp/ que se borra al terminar.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kitlib.runtime import configure

TRAZA = ["tests.test_recetas.TrazaTests"]
RENOMBRAR = ["tests.test_transformaciones.RenombrarTests"]
NORMALIZAR = ["tests.test_transformaciones.NormalizarTests"]
REEMPLAZAR = ["tests.test_transformaciones.ReemplazarTests"]
COMPLETAR = ["tests.test_transformaciones.CompletarTests"]
DUPLICADOS = ["tests.test_transformaciones.DuplicadosTests"]
ENCABEZADOS = ["tests.test_transformaciones.EncabezadosTests"]
CONTRATO = ["tests.test_contrato"]
ERRORES = ["tests.test_contrato.ErroresTests"]
RESULTADOS = ["tests.test_contrato.ResultadosTests", "tests.test_contrato.PrivacidadTests"]
SQL = ["tests.test_sql", "tests.test_esquemas"]
ESQUEMAS = ["tests.test_esquemas.EquivalenciaTests.test_examples_and_valid_cases_pass_both",
            "tests.test_esquemas.EquivalenciaTests.test_invalid_cases_are_rejected_by_both_or_are_listed_semantic_rules"]
EJEMPLOS = ["tests.test_recetas_ejemplo"]
COMPATIBILIDAD = ["tests.test_compatibilidad.CompatibilidadTests"]
COMPACTO = ["tests.test_compatibilidad.CompactoTests"]
MUTATIONS = [
    # Etapa 2: trazabilidad
    ("incidencias con fila intermedia", "src/kitlib/traza.py",
     "    numbers = table.row_numbers or list(range(2, len(table.rows) + 2))\n    by_number",
     "    return issues\n    numbers = table.row_numbers or list(range(2, len(table.rows) + 2))\n    by_number", TRAZA),
    ("select pierde la procedencia", "src/kitlib/operations.py",
     "                if ORIGEN in r:\n                    row[ORIGEN] = r[ORIGEN]\n", "", TRAZA),
    ("consolidar ignora la fila real", "src/kitlib/operations.py",
     '"__fila_origen": str(origin[2] if origin else rowno)', '"__fila_origen": str(rowno)', TRAZA),
    ("filtro no registra excluidas", "src/kitlib/operations.py",
     'trace["excluidas"].append((index, "filter"', 'None and trace["excluidas"].append((index, "filter"', TRAZA),
    ("JSON publica la procedencia", "src/kitlib/tableio.py",
     "json.dumps(public_row(row), ensure_ascii=False",
     "json.dumps({k: str(v) for k, v in row.items()}, ensure_ascii=False", TRAZA),
    ("invariante siempre cumple", "src/kitlib/recetas.py",
     'broken = [c["regla"] for c in checks if not c["cumple"]]', "broken: list = []", TRAZA),
    ("convert no registra cambios", "src/kitlib/operations.py",
     "if trace is not None and row[col] != before:", "if False:", TRAZA),
    # Etapa 3: renombrar
    ("rename acepta dos salidas iguales", "src/kitlib/operations.py",
     "        if repeated:\n            raise ValueError(\"rename: dos columnas",
     "        if False:\n            raise ValueError(\"rename: dos columnas", RENOMBRAR),
    ("rename pisa una columna existente", "src/kitlib/operations.py",
     "            if clash:\n                raise ValueError(\"rename: el nombre nuevo choca",
     "            if False:\n                raise ValueError(\"rename: el nombre nuevo choca", RENOMBRAR),
    ("rename ignora columnas inexistentes", "src/kitlib/operations.py",
     "            require_columns(current, list(mapping))\n", "", RENOMBRAR),
    ("rename pierde la procedencia", "src/kitlib/operations.py",
     "{mapping.get(k, k): v for k, v in r.items()}", "{mapping.get(k, k): v for k, v in r.items() if k != ORIGEN}",
     RENOMBRAR),
    ("JSON acepta claves repetidas", "src/kitlib/tableio.py",
     "    if repeated:\n        raise ValueError(\"Clave JSON repetida",
     "    if False:\n        raise ValueError(\"Clave JSON repetida", RENOMBRAR),
    # Etapa 3: normalizar
    ("normalize toca todas las columnas", "src/kitlib/operations.py",
     "            for col in step[\"columns\"]:\n                distinct_before",
     "            for col in current.columns:\n                distinct_before", NORMALIZAR),
    ("normalize solo recorta", "src/kitlib/operations.py",
     'after = " ".join(str(before).split())', "after = str(before).strip()", NORMALIZAR),
    ("normalize no registra cambios", "src/kitlib/operations.py",
     "trace[\"cambios\"].append((index, label, col", "None and trace[\"cambios\"].append((index, label, col",
     NORMALIZAR),
    ("normalize invierte mayúsculas", "src/kitlib/operations.py",
     'after = after.upper() if case == "upper" else after.lower() if case == "lower" else after',
     'after = after.lower() if case == "upper" else after.upper() if case == "lower" else after', NORMALIZAR),
    ("normalize quita tildes", "src/kitlib/operations.py",
     'after = " ".join(str(before).split())',
     'after = " ".join(str(before).split()).replace("é", "e").replace("É", "E")', NORMALIZAR),
    ("normalize no cuenta valores unificados", "src/kitlib/operations.py",
     "                if merged:\n", "                if False:\n", NORMALIZAR),
    # Etapa 3: reemplazar
    ("replace aproxima recortando espacios", "src/kitlib/operations.py",
     "                value = row[col]\n                if isinstance(value, str) and value in mapping:",
     "                value = row[col].strip() if isinstance(row[col], str) else row[col]\n"
     "                if isinstance(value, str) and value in mapping:", REEMPLAZAR),
    ("replace trata destinos como desconocidos", "src/kitlib/operations.py",
     "elif not empty(value) and value not in canonical:", "elif not empty(value):", REEMPLAZAR),
    ("replace no registra el cambio", "src/kitlib/operations.py",
     'trace["cambios"].append((index, "replace"', 'None and trace["cambios"].append((index, "replace"', REEMPLAZAR),
    ("replace exclude no guarda la fila", "src/kitlib/operations.py",
     'trace["excluidas"].append((index, "replace"', 'None and trace["excluidas"].append((index, "replace"',
     REEMPLAZAR),
    ("replace keep sin advertencia", "src/kitlib/operations.py",
     'warnings.append({"origen": origin[1] if origin else table.source',
     'None and warnings.append({"origen": origin[1] if origin else table.source', REEMPLAZAR),
    ("replace error continúa", "src/kitlib/operations.py",
     '                    if unknown == "error":\n', '                    if False:\n', REEMPLAZAR),
    ("replace toca celdas vacías", "src/kitlib/operations.py",
     "elif not empty(value) and value not in canonical:", "elif value not in canonical:", REEMPLAZAR),
    # Etapa 3: completar desde referencia
    ("completar elige la primera de varias", "src/kitlib/operations.py",
     'else "ambiguas" if len(matches) > 1 else "completadas")', 'else "completadas")', COMPLETAR),
    ("completar rellena ceros en la clave", "src/kitlib/operations.py",
     "        key = tuple(row[c] for c in keys)\n        matches",
     "        key = tuple((row[c] or '').zfill(4) for c in keys)\n        matches", COMPLETAR),
    ("completar pisa datos presentes", "src/kitlib/operations.py",
     'fill = existing == "completar_vacios" and empty(before) and not empty(value)',
     'fill = existing == "completar_vacios" and not empty(value)', COMPLETAR),
    ("completar calla claves vacías de la referencia", "src/kitlib/operations.py",
     'ref_issues.append(issue("clave_vacia_en_referencia"', 'None and ref_issues.append(issue("clave_vacia_en_referencia"',
     COMPLETAR),
    ("completar calla claves duplicadas de la referencia", "src/kitlib/operations.py",
     "        if len(matches) > 1:\n            ref_issues.extend(", "        if False:\n            ref_issues.extend(",
     COMPLETAR),
    ("completar no registra cambios", "src/kitlib/operations.py",
     'changes.append(("", f"completar ({existing})"', 'None and changes.append(("", f"completar ({existing})"',
     COMPLETAR),
    ("completar sin invariante", "src/kitlib/traza.py", 'if op == "completar" and outputs:', "if False:", COMPLETAR),
    ("completar admite columnas ya presentes", "src/kitlib/operations.py",
     'if present and existing == "error":', "if False:", COMPLETAR),
    # Etapa 3: duplicados
    ("duplicados no distingue idénticas", "src/kitlib/operations.py",
     "            if twin is None:\n                distinct.append(p)", "            if True:\n                distinct.append(p)",
     DUPLICADOS),
    ("duplicados compara columnas de procedencia", "src/kitlib/operations.py",
     'columns = compare_columns or [c for c in table.columns if not c.startswith("__")]',
     "columns = compare_columns or list(table.columns)", DUPLICADOS),
    ("duplicados elige en un empate", "src/kitlib/operations.py",
     'if len(tied) == 1 or tie != "conflicto":', "if True:", DUPLICADOS),
    ("duplicados ignora fechas inválidas", "src/kitlib/operations.py",
     "            if any(v is None for v in dates):", "            if False:", DUPLICADOS),
    ("duplicados conserva claves vacías", "src/kitlib/operations.py",
     "        if any(empty(v) for v in key):\n            fate.update(", "        if False:\n            fate.update(",
     DUPLICADOS),
    ("duplicados sin motivos", "src/kitlib/operations.py", "motives[origin[1:]] = [why]", "pass", DUPLICADOS),
    ("duplicados último toma el primero", "src/kitlib/operations.py",
     "            winner = distinct[-1]", "            winner = distinct[0]", DUPLICADOS),
    ("duplicados sin invariante", "src/kitlib/traza.py", 'if op == "duplicados" and outputs:', "if False:",
     DUPLICADOS),
    # Etapa 3: encabezados y pies
    ("encabezado no omite títulos", "src/kitlib/tableio.py",
     "            for _ in range(opts.header_row - 1):  # títulos", "            for _ in range(0):  # títulos",
     ENCABEZADOS),
    ("filas numeradas desde 2", "src/kitlib/tableio.py",
     "enumerate(records, header_row + 1)", "enumerate(records, 2)", ENCABEZADOS),
    ("exclusión sin registro", "src/kitlib/tableio.py",
     "            table.excluded.append((rowno, reason, [literal(v) for v in values]))", "            pass", ENCABEZADOS),
    ("empieza_con como contiene", "src/kitlib/tableio.py",
     'text.startswith(cond["empieza_con"])', 'cond["empieza_con"] in text', ENCABEZADOS),
    ("exclusión solo en filas completas", "src/kitlib/tableio.py",
     "reason = _exclusion(values, columns, conditions) if conditions else None",
     "reason = _exclusion(values, columns, conditions) if conditions and len(values) == len(columns) else None",
     ENCABEZADOS),
    ("JSON acepta fila_encabezado", "src/kitlib/receta_validacion.py",
     'elif entry.ruta.suffix.lower() == ".json" and (entry.opts.header_row != 1 or entry.opts.exclude_rows):',
     "elif False:", ENCABEZADOS),
    ("invariante de lectura ignora excluidas", "src/kitlib/recetas.py",
     '"cumple": table.scanned == len(table.rows) + malformed + len(table.excluded)}',
     '"cumple": table.scanned >= 0}', ENCABEZADOS),
    ("igual ignora mayúsculas", "src/kitlib/tableio.py",
     'if "igual" in cond and text == cond["igual"]:', 'if "igual" in cond and text.lower() == cond["igual"].lower():',
     ENCABEZADOS),
    # Etapa 4: esquemas (rompen el esquema o el validador; deben divergir y detectarse)
    ("esquema de plan admite parámetros extra", "src/kitlib/esquemas.py",
     'steps.append({"type": "object", "required": sorted(required | {"op"}), "additionalProperties": False,',
     'steps.append({"type": "object", "required": sorted(required | {"op"}), "additionalProperties": True,',
     ESQUEMAS),
    ("esquema permite separar en cualquier paso", "src/kitlib/esquemas.py",
     '"incidencias": {"enum": list(INCIDENCIAS) if separable else ["detener"]},',
     '"incidencias": {"enum": list(INCIDENCIAS)},', ESQUEMAS),
    ("esquema con otro máximo de sample", "src/kitlib/esquemas.py",
     '"maximum": SAMPLE_MAX}', '"maximum": SAMPLE_MAX + 10}', ESQUEMAS),
    ("esquema admite renombrar a espacios", "src/kitlib/esquemas.py",
     '"propertyNames": {"minLength": 1}, "additionalProperties": TEXT}',
     '"propertyNames": {"minLength": 1}, "additionalProperties": {"type": "string"}}', ESQUEMAS),
    ("esquema admite fila_encabezado 0", "src/kitlib/esquemas.py",
     '"fila_encabezado": {"type": "integer", "minimum": 1}', '"fila_encabezado": {"type": "integer", "minimum": 0}',
     ESQUEMAS),
    ("esquema admite cualquier versión", "src/kitlib/esquemas.py",
     'top = {"version": {"const": VERSION},', 'top = {"version": {"type": "integer"},', ESQUEMAS),
    ("validador sin comprobar column de convert", "src/kitlib/operations.py",
     '    if op == "convert" and not isinstance(step["column"], str):', "    if False:", ESQUEMAS),
    ("validador admite value lista", "src/kitlib/operations.py",
     '        if isinstance(step["value"], (list, dict)):', "        if False:", ESQUEMAS),
    ("validador admite versión true", "src/kitlib/receta_validacion.py",
     'elif raw["version"] != VERSION or isinstance(raw["version"], bool):', 'elif raw["version"] != VERSION:',
     ESQUEMAS),
    # Etapa 4: catálogo y comprobar
    ("comprobar siempre válido", "src/kitlib/contrato.py", "    code = 2 if found else 0", "    code = 0", CONTRATO),
    ("comprobar exige la entrada principal", "src/kitlib/receta_validacion.py",
     "            continue  # comprobar sin datos", "            pass  # comprobar sin datos", CONTRATO),
    ("catálogo con otra versión", "src/kitlib/contrato.py", '"version_kit": __version__,', '"version_kit": "x",',
     CONTRATO),
    ("comprobar confunde planes y reglas", "src/kitlib/contrato.py",
     '        if "steps" in config:\n            return "plan"', '        if "steps" in config:\n            return "reglas"',
     CONTRATO),
    ("código sin registrar", "src/kitlib/codigos.py",
     '    "valor_no_unico": "Valor repetido en una columna unique",\n', "", CONTRATO),
    ("comprobar sin aviso de alcance", "src/kitlib/contrato.py",
     '"version_esquema": SCHEMA_VERSION, "alcance": ALCANCE,', '"version_esquema": SCHEMA_VERSION, "alcance": "",',
     CONTRATO),
    ("catálogo pierde una operación", "src/kitlib/contrato.py",
     "for op, (allowed, required) in PARAMS.items()},", "for op, (allowed, required) in PARAMS.items() if op != 'completar'},",
     CONTRATO),
    # Etapa 4: errores estructurados
    ("error de argumento sin campo", "src/kitlib/runtime.py",
     "        return exc.codigo, exc.campo, exc.sugerencia", "        return exc.codigo, None, exc.sugerencia", ERRORES),
    ("archivo inexistente como error genérico", "src/kitlib/runtime.py",
     '        return "archivo_no_encontrado", None, "Revise las rutas y las comillas"',
     '        return "error_de_ejecucion", None, "Revise las rutas y las comillas"', ERRORES),
    ("codificación sin código propio", "src/kitlib/runtime.py",
     "    if isinstance(exc, UnicodeError):\n        return \"codificacion_incorrecta\"",
     "    if False:\n        return \"codificacion_incorrecta\"", ERRORES),
    ("errores también en la salida de texto", "src/kitlib/cli.py",
     '        print(f"{summary[\'estado\']} | filas={summary[\'filas_procesadas\']} | "',
     '        print(summary.get("errores", ""))\n        print(f"{summary[\'estado\']} | filas={summary[\'filas_procesadas\']} | "',
     ERRORES),
    ("receta inexistente sin campo", "src/kitlib/receta_cli.py",
     'raise KitError("No existe la receta", "--receta",', 'raise KitError("No existe la receta", None,', ERRORES),
    ("mensaje de KitError oculto", "src/kitlib/runtime.py",
     "    if type(exc) in (ValueError, KitError):", "    if type(exc) is ValueError:", ERRORES),
    # Etapa 4: resultados y privacidad
    ("resultados sin tope", "src/kitlib/contrato.py", "        limit = min(args.n, MAX_N)", "        limit = args.n",
     RESULTADOS),
    ("resultados cuenta copias exportadas", "src/kitlib/contrato.py",
     'if p.is_dir() and p.name not in exported]', "if p.is_dir()]", RESULTADOS),
    ("resultados toma la ejecución más antigua", "src/kitlib/contrato.py",
     "        folder = max(runs, key=lambda p: (p.stat().st_mtime, p.name))",
     "        folder = min(runs, key=lambda p: (p.stat().st_mtime, p.name))", RESULTADOS),
    ("resultados sin aviso de incompleta", "src/kitlib/contrato.py",
     '        result["aviso"] = "Ejecución incompleta o en curso: no usar sus resultados"', "        pass", RESULTADOS),
    ("consultar ignora ocultar valores", "src/kitlib/cli.py",
     '    if args.ocultar_valores and args.command == "consultar":\n        args.show = 0',
     '    if args.ocultar_valores and args.command == "consultar":\n        pass', RESULTADOS),
    ("inspeccionar ignora ocultar valores", "src/kitlib/cli.py",
     '    if args.ocultar_valores and args.command == "inspeccionar":\n        args.sample = 0',
     '    if args.ocultar_valores and args.command == "inspeccionar":\n        pass', RESULTADOS),
    ("receta ignora ocultar valores", "src/kitlib/receta_cli.py",
     '                step.spec = {**step.spec, "sample": 0}', "                pass", RESULTADOS),
    # Etapa 4: SQL
    ("tipo por tabla se aplica a todas", "src/kitlib/operations.py",
     '(declared if kind == "number" else as_text).add((name.lower(), col.lower()))',
     '(declared if kind == "number" else as_text).update((n.lower(), col.lower()) for n in tables)', SQL),
    ("tipos ignorados", "src/kitlib/operations.py",
     '(declared if kind == "number" else as_text).add((name.lower(), col.lower()))', "pass", SQL),
    ("texto declarado sigue sospechoso", "src/kitlib/operations.py",
     "_decimal_text_columns(tables, numeric, opts, read) - declared - as_text)",
     "_decimal_text_columns(tables, numeric, opts, read) - declared)", SQL),
    ("límite del detector invertido", "src/kitlib/operations.py",
     "if suspects and sum(len(t.rows) for t in tables.values()) > detector_max_rows:",
     "if suspects and sum(len(t.rows) for t in tables.values()) < detector_max_rows:", SQL),
    ("detector omitido en silencio", "src/kitlib/operations.py",
     '    if details.get("detector_omitido_filas"):', "    if False:", SQL),
    ("detector no se puede apagar", "src/kitlib/operations.py",
     "opts, read) - declared - as_text) if detector else []", "opts, read) - declared - as_text)", SQL),
    ("receta admite tipos de tablas ausentes", "src/kitlib/receta_validacion.py",
     'elif isinstance(spec.get("tablas"), dict) and set(tipos) - set(spec["tablas"]):', "elif False:", SQL),
    ("número y texto a la vez", "src/kitlib/operations.py", "    if declared & as_text:", "    if False:", SQL),
    # Etapa 5: recetas de ejemplo con esperados a mano (rompen un paso que esas recetas usan)
    ("completar copia solo la primera columna", "src/kitlib/operations.py",
     "        for col in columns:\n            value = match[col]", "        for col in columns[:1]:\n            value = match[col]",
     EJEMPLOS),
    ("duplicados idénticas van a conflictos", "src/kitlib/operations.py",
     "            twin = next((d for d in distinct if values(d) == values(p)), None)", "            twin = None", EJEMPLOS),
    ("exportar omite el xlsx pedido", "src/kitlib/recetas.py", '    if "xlsx" in formats:', "    if False:", EJEMPLOS),
    ("rename deja los nombres antiguos en las filas", "src/kitlib/operations.py",
     "{mapping.get(k, k): v for k, v in r.items()}", "{k: v for k, v in r.items()}", EJEMPLOS),
    # Etapa 5: compatibilidad entre comandos sueltos y pasos de receta
    ("receta validar intercambia aceptadas y rechazadas", "src/kitlib/recetas.py",
     '{"aceptadas": tables["validos"], "rechazadas": tables["invalidos"]}',
     '{"aceptadas": tables["invalidos"], "rechazadas": tables["validos"]}', COMPATIBILIDAD),
    ("receta consolidar invierte las entradas", "src/kitlib/recetas.py",
     'merge_tables([(ref, get(ref), None) for ref in step.refs["entradas"]])',
     'merge_tables([(ref, get(ref), None) for ref in reversed(step.refs["entradas"])])', COMPATIBILIDAD),
    ("receta transformar ignora las opciones de lectura", "src/kitlib/recetas.py",
     'tables, issues, details = transform(get(step.refs["entrada"]), step.config, step.opts, trace)',
     'tables, issues, details = transform(get(step.refs["entrada"]), step.config, step.opts.__class__(), trace)',
     COMPATIBILIDAD + EJEMPLOS),
    # Etapa 5: salidas compactas
    ("resultados sin tope de pasos", "src/kitlib/contrato.py", 'for p in manifest["pasos"][:30]])',
     'for p in manifest["pasos"]])', COMPACTO),
    ("resultados sin tope de archivos", "src/kitlib/contrato.py",
     'if not p.name.startswith("."))[:40]', 'if not p.name.startswith("."))', COMPACTO),
    ("resultados sin tope de códigos", "src/kitlib/contrato.py", "key=lambda kv: -kv[1])[:15])", "key=lambda kv: -kv[1]))",
     COMPACTO),
    ("resultados sin recorte del detalle", "src/kitlib/contrato.py",
     "{k: (str(v)[:200] if isinstance(v, str) else v) for k, v in item.items()}", "{k: v for k, v in item.items()}",
     COMPACTO),
]


def run(selected):
    configure()  # crea tmp/ dentro del proyecto si falta
    missing = undetected = 0
    for name, path, old, new, tests in selected:
        with tempfile.TemporaryDirectory(prefix="mutante-", dir=ROOT / "tmp") as folder:
            copy = Path(folder)
            for item in ("src", "tests", "recetas", "examples", "schemas", "docs", "kit.py", "pyproject.toml"):
                source = ROOT / item
                if source.is_dir():
                    shutil.copytree(source, copy / item)
                else:
                    shutil.copy2(source, copy / item)
            target = copy / path
            text = target.read_text(encoding="utf-8")
            if text.count(old) != 1:
                print(f"PATRÓN NO ENCONTRADO: {name} ({path}); actualice la mutación")
                missing += 1
                continue
            target.write_text(text.replace(old, new), encoding="utf-8")
            result = subprocess.run([sys.executable, "-B", "-m", "unittest", *tests], cwd=copy,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace")
            lines = (result.stdout + result.stderr).strip().splitlines()
            detected = result.returncode != 0
            undetected += not detected
            print(f"{'DETECTADA' if detected else 'NO DETECTADA'}: {name} → {lines[-1] if lines else ''}")
    print(f"{len(selected) - missing - undetected}/{len(selected)} detectadas")
    return 2 if missing else 1 if undetected else 0


if __name__ == "__main__":
    pattern = " ".join(sys.argv[1:]).lower()
    raise SystemExit(run([m for m in MUTATIONS if pattern in m[0].lower()]))

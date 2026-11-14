"""Puente entre la página y el kit. Toda la lógica de la interfaz está aquí, en Python, para probarla
con unittest; el JavaScript solo pinta el JSON que devuelven estos métodos.

Principio: la interfaz no calcula. El puente ejecuta la línea de comandos del kit (`kit.py`, como lo
haría una persona en la terminal) y lee lo que el kit escribió: el resumen `--json`, `manifiesto.json`,
`report.json`, `audit.json`, las tablas JSON y los `*_procedencia.csv` e `incidencias.json` de cada paso.
No valida, no transforma, no cuenta filas por su cuenta: cada número de la pantalla sale de esos archivos.

Se invoca la CLI (y no las funciones internas) porque así la interfaz usa exactamente el mismo camino que
`./kit ejecutar`, no puede alterar el proceso del kit y una ejecución larga no bloquea el servidor.

Carpetas: lee solo data/, examples/, recetas/ y results/; escribe donde escribe el kit (results/ y, para
las inspecciones de la pantalla 1, tmp/interfaz/) más las copias subidas en data/interfaz-subidas/.
"""
import base64
import csv
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4

from kitlib import __version__
from kitlib.receta_modelo import SEPARATED
from kitlib.runtime import ROOT
from kitlib.interfaz.explicaciones import explicar

EXTENSIONES = (".csv", ".xlsx", ".xlsm")  # lo que el kit lee sin necesitar más datos (las tablas JSON no se
# distinguen de un plan o unas reglas sin leerlas, así que no se listan)
LIMITE_SUBIDA = 20 * 1024 * 1024  # bytes del archivo subido; documentado en docs/tools/interfaz.md
TOPE_FILAS = 200  # filas mostradas por pestaña; el archivo completo queda en la carpeta de la ejecución
NOMBRE_SUBIDA = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ ()-]{0,99}")
NOMBRE_EJECUCION = re.compile(r"[A-Za-z0-9_-]{1,100}")

TIPO_FRANJA = {"completada": "exito", "completada_con_incidencias": "incidencias", "fallida": "fallo",
               "en_curso": "curso"}
TITULO_FALLO = {"detenida_por_politica": "Detenida por la política de la receta",
                "error_de_ejecucion": "Fallida por un error de ejecución",
                "interrumpida": "Interrumpida antes de terminar"}


class PeticionInvalida(ValueError):
    """Petición que el puente rechaza; `http` es el código de respuesta."""

    def __init__(self, mensaje, http=400):
        super().__init__(mensaje)
        self.http = http


class Ocupado(PeticionInvalida):
    def __init__(self):
        super().__init__("Ya hay una ejecución en marcha; espere a que termine", 409)


def _ejecutor_cli(argumentos, cwd):
    """Ejecuta kit.py como lo haría la terminal y devuelve (código de salida, stdout)."""
    result = subprocess.run([sys.executable, "-B", str(cwd / "kit.py"), *argumentos], cwd=cwd,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result.returncode, result.stdout


def _abridor_sistema(ruta):
    """Abre una carpeta o un archivo con el explorador o la aplicación del sistema."""
    if sys.platform.startswith("win"):
        os.startfile(str(ruta))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(ruta)])
    else:
        subprocess.Popen(["xdg-open", str(ruta)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _json_salida(stdout):
    """El resumen --json del kit, o None si la salida no fue JSON (fallo inesperado)."""
    try:
        value = json.loads(stdout)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _leer_json(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _leer_csv(path, delimiter):
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter=delimiter))


class Puente:
    def __init__(self, raiz=None, ejecutor=None, abridor=None):
        self.raiz = Path(raiz or ROOT).resolve()
        self.ejecutor = ejecutor or (lambda argumentos: _ejecutor_cli(argumentos, ROOT))
        self.abridor = abridor or _abridor_sistema
        self.lectura = {n: self.raiz / n for n in ("data", "examples", "recetas", "results")}
        self.subidas = self.raiz / "data" / "interfaz-subidas"
        self.temporales = self.raiz / "tmp" / "interfaz"
        self._candado = threading.Lock()
        self._ejecuciones: dict[str, dict] = {}  # nombre → {"hilo", "codigo", "salida"}
        self._ultima: str | None = None

    # ------------------------------------------------------------------ rutas

    def _relativa(self, ruta):
        """Ruta relativa a la raíz, en formato POSIX, para la página."""
        return ruta.resolve().relative_to(self.raiz).as_posix()

    def _permitida(self, relativa, carpetas, debe_existir=True):
        """Resuelve una ruta relativa dentro de las carpetas dadas. Rechaza absolutas, `..`, nombres vacíos
        y enlaces que salgan de ellas (se comprueba la ruta real)."""
        if not isinstance(relativa, str) or not relativa.strip():
            raise PeticionInvalida("Falta la ruta")
        pure = PurePosixPath(relativa.replace("\\", "/"))
        if pure.is_absolute() or re.match(r"^[A-Za-z]:", relativa) or ".." in pure.parts or "" in pure.parts:
            raise PeticionInvalida("Ruta no admitida: use una ruta relativa dentro de las carpetas permitidas")
        candidate = (self.raiz / Path(*pure.parts)).resolve()
        bases = [self.lectura[c].resolve() for c in carpetas]
        if not any(candidate == b or candidate.is_relative_to(b) for b in bases):
            raise PeticionInvalida("Ruta fuera de las carpetas permitidas: " + ", ".join(carpetas) + "/")
        if debe_existir and not candidate.exists():
            raise PeticionInvalida("No existe: " + relativa[:120], 404)
        return candidate

    def _argumento_kit(self, ruta):
        """Ruta tal como la recibiría la terminal: relativa a la raíz real del kit (cwd de kit.py)."""
        return str(ruta.resolve().relative_to(ROOT)) if ruta.resolve().is_relative_to(ROOT) else str(ruta)

    # ------------------------------------------------------------------ pantalla 1: archivo

    def estado(self):
        return {"version": __version__, "ejecutando": self._ejecutando(), "ultima_ejecucion": self._ultima,
                "carpetas": {"lee": ["data/", "examples/", "recetas/", "results/"],
                             "escribe": ["results/ (ejecuciones del kit)", "tmp/interfaz/ (inspecciones)",
                                         "data/interfaz-subidas/ (copias de archivos subidos)"]},
                "limites": {"subida_bytes": LIMITE_SUBIDA, "tope_filas": TOPE_FILAS, "extensiones": list(EXTENSIONES)},
                "local": "Todo local · tus archivos no salen de este equipo"}

    def archivos(self):
        """Archivos de data/ y examples/ con extensión que el kit lee. data/bitacora/ es privada y no se lista."""
        found = []
        for name in ("data", "examples"):
            base = self.lectura[name]
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in EXTENSIONES or path.name.startswith("."):
                    continue
                if base.name == "data" and path.relative_to(base).parts[:1] == ("bitacora",):
                    continue
                found.append({"ruta": self._relativa(path), "nombre": path.name, "carpeta": name,
                              "bytes": path.stat().st_size,
                              "subida": path.resolve().is_relative_to(self.subidas.resolve())})
        return found

    def inspeccionar(self, ruta):
        """`kit inspeccionar RUTA --json --sample 0`. Sin valores de celdas (sample 0). Si el kit sugiere otro
        delimitador (`sugerencia`), se repite una vez con esa opción del propio kit."""
        path = self._permitida(ruta, ("data", "examples"))
        self.temporales.mkdir(parents=True, exist_ok=True)
        delimiter = ","
        code, summary = 2, {}
        for _ in range(2):
            name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-interfaz-" + uuid4().hex[:8]
            code, out = self.ejecutor(["inspeccionar", self._argumento_kit(path), "--json", "--sample", "0",
                                       "--delimiter", delimiter, "--output", self._argumento_kit(self.temporales),
                                       "--run-name", name])
            summary = _json_salida(out)
            if summary is None:
                return {"ruta": ruta, "nombre": path.name, "estado": "error", "codigo_salida": code,
                        "error": "El kit no devolvió un resumen legible", "tablas": []}
            hint = re.fullmatch(r"--delimiter '(.*)'", summary.get("sugerencia") or "")
            if hint and delimiter == ",":
                delimiter = hint.group(1)
                continue
            break
        tables = [{"hoja": t.get("hoja"), "filas": t.get("filas"), "alcance": t.get("alcance"),
                   "columnas": t.get("columnas", [])} for t in summary.get("tablas", [])]
        return {"ruta": ruta, "nombre": path.name, "bytes": path.stat().st_size, "estado": summary.get("estado"),
                "codigo_salida": code, "delimitador": delimiter, "tablas": tables,
                "incidencias": summary.get("incidencias", 0), "advertencias": summary.get("advertencias", 0),
                "incidencias_por_codigo": summary.get("incidencias_por_codigo", {}),
                "advertencias_por_codigo": summary.get("advertencias_por_codigo", {}),
                "error": summary.get("error"), "errores": summary.get("errores", []),
                "nota": "Cifras de «inspeccionar» del kit" + (f" con --delimiter '{delimiter}' (sugerido por el kit)"
                                                               if delimiter != "," else "")}

    def subir(self, nombre, contenido_base64):
        """Guarda una COPIA en data/interfaz-subidas/ sin pisar nada. El original del usuario no se toca."""
        if not isinstance(nombre, str) or not NOMBRE_SUBIDA.fullmatch(nombre) or nombre != Path(nombre).name:
            raise PeticionInvalida("Nombre de archivo no admitido: letras, dígitos, punto, guion, espacio; "
                                   "hasta 100 caracteres")
        if Path(nombre).suffix.lower() not in EXTENSIONES:
            raise PeticionInvalida("Extensión no admitida: " + ", ".join(EXTENSIONES))
        if not isinstance(contenido_base64, str):
            raise PeticionInvalida("Falta el contenido")
        if len(contenido_base64) > LIMITE_SUBIDA * 4 // 3 + 4:
            raise PeticionInvalida(f"Archivo mayor que el límite de {LIMITE_SUBIDA // (1024 * 1024)} MiB", 413)
        try:
            data = base64.b64decode(contenido_base64, validate=True)
        except (ValueError, TypeError):
            raise PeticionInvalida("Contenido no es base64 válido") from None
        if len(data) > LIMITE_SUBIDA:
            raise PeticionInvalida(f"Archivo mayor que el límite de {LIMITE_SUBIDA // (1024 * 1024)} MiB", 413)
        self.subidas.mkdir(parents=True, exist_ok=True)
        stem, suffix = Path(nombre).stem, Path(nombre).suffix
        for n in range(1, 1000):
            target = self.subidas / (nombre if n == 1 else f"{stem}-{n}{suffix}")
            try:
                with target.open("xb") as stream:  # creación exclusiva: nunca pisa un archivo existente
                    stream.write(data)
            except FileExistsError:
                continue
            return {"ruta": self._relativa(target), "nombre": target.name, "bytes": len(data),
                    "renombrado": target.name != nombre,
                    "aviso": "Se guardó una copia en data/interfaz-subidas/" + target.name
                             + ". Tu archivo original no se tocó."}
        raise PeticionInvalida("Demasiadas copias con ese nombre; cambie el nombre del archivo")

    # ------------------------------------------------------------------ pantalla 2: receta

    def recetas(self):
        """Recetas de recetas/*.json. Título = `nombre`, texto = `descripcion` (campos que el esquema ya
        admite). Las entradas distintas de la principal se listan tal como la receta las declara."""
        found = []
        base = self.lectura["recetas"]
        for path in sorted(base.glob("*.json")) if base.is_dir() else []:
            item = {"ruta": self._relativa(path), "archivo": path.name, "titulo": path.stem, "descripcion": "",
                    "pasos": [], "entradas": [], "error": None}
            try:
                recipe = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(recipe, dict):
                    raise ValueError("no es un objeto")
            except ValueError as exc:
                item["error"] = "No se pudo leer la receta: " + str(exc)[:120]
                found.append(item)
                continue
            if isinstance(recipe.get("nombre"), str) and recipe["nombre"].strip():
                item["titulo"] = recipe["nombre"]
            if isinstance(recipe.get("descripcion"), str):
                item["descripcion"] = recipe["descripcion"]
            steps = recipe["pasos"] if isinstance(recipe.get("pasos"), list) else []
            item["pasos"] = [{"nombre": str(s.get("nombre", "?")), "op": str(s.get("op", "?"))}
                             for s in steps if isinstance(s, dict)]
            entries = recipe["entradas"] if isinstance(recipe.get("entradas"), dict) else {}
            for name, entry in entries.items():
                entry = entry if isinstance(entry, dict) else {}
                item["entradas"].append({"nombre": name, "principal": entry.get("principal") is True,
                                         "ruta": entry.get("ruta") if isinstance(entry.get("ruta"), str) else None,
                                         "descripcion": entry.get("descripcion") if isinstance(entry.get("descripcion"),
                                                                                                str) else ""})
            others = [e for e in item["entradas"] if not e["principal"]]
            item["otras_entradas"] = ("Además del archivo principal, la receta usa: " + ", ".join(
                f"{e['nombre']} ({e['ruta'] or 'sin archivo declarado: se pide con --entrada'})" for e in others)
                if others else "")
            found.append(item)
        return found

    def _argumentos_ejecutar(self, archivo, receta):
        path = self._permitida(archivo, ("data", "examples"))
        recipe = self._permitida(receta, ("recetas",))
        if recipe.suffix.lower() != ".json":
            raise PeticionInvalida("La receta debe ser un archivo .json de recetas/")
        return [self._argumento_kit(path), "--receta", self._argumento_kit(recipe)]

    # ------------------------------------------------------------------ pantalla 3: ejecutar

    def vista_previa(self, archivo, receta):
        """`kit ejecutar ARCHIVO --receta R --vista-previa --json`: el alcance se muestra con las palabras del kit."""
        code, out = self.ejecutor(["ejecutar", *self._argumentos_ejecutar(archivo, receta), "--vista-previa", "--json"])
        summary = _json_salida(out)
        if summary is None:
            return {"estado": "error", "codigo_salida": code, "titulo": "La vista previa no devolvió un resumen",
                    "alcance": "", "entradas": [], "pasos": [], "errores": [], "avisos": []}
        if summary.get("estado") != "vista_previa":
            return {"estado": "error", "codigo_salida": code, "titulo": summary.get("error") or "Error del kit",
                    "alcance": "", "entradas": [], "pasos": [], "errores": summary.get("errores", []), "avisos": []}
        steps = [{"numero": s["numero"], "nombre": s["nombre"], "op": s["op"],
                  "produce": s.get("produce", []), "columnas": s.get("columnas"), "motivo": s.get("motivo"),
                  "incidencias_previstas": s.get("incidencias_previstas", []),
                  "politica": s.get("politica", {}).get("incidencias")} for s in summary.get("pasos", [])]
        entries = [{"nombre": e["nombre"], "ruta": e.get("ruta"), "encabezado": e.get("encabezado"),
                    "columnas": e.get("columnas"), "motivo": e.get("motivo"), "delimiter": e.get("delimiter")}
                   for e in summary.get("entradas", [])]
        return {"estado": "vista_previa", "codigo_salida": code, "titulo": "Vista previa de " + str(summary.get("receta")),
                "alcance": summary.get("aviso", ""), "destino": summary.get("destino", ""), "entradas": entries,
                "pasos": steps, "errores": summary.get("errores", []), "avisos": summary.get("avisos", [])}

    def _ejecutando(self):
        return any(r["hilo"].is_alive() for r in self._ejecuciones.values())

    def iniciar_ejecucion(self, archivo, receta):
        """Lanza `kit ejecutar` en un hilo. Una sola ejecución a la vez (409 si hay otra)."""
        argumentos = self._argumentos_ejecutar(archivo, receta)
        if not self._candado.acquire(blocking=False):
            raise Ocupado()
        try:
            self.lectura["results"].mkdir(parents=True, exist_ok=True)
            name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-interfaz-" + uuid4().hex[:10]
            record: dict = {"codigo": None, "salida": None, "archivo": archivo, "receta": receta}
            command = ["ejecutar", *argumentos, "--output", self._argumento_kit(self.lectura["results"]),
                       "--run-name", name, "--json"]

            def work():
                try:
                    record["codigo"], record["salida"] = self.ejecutor(command)
                except Exception as exc:  # el error se muestra; el candado se libera siempre
                    record["codigo"], record["salida"] = 2, json.dumps({"estado": "error", "error": str(exc)[:200]})
                finally:
                    self._candado.release()

            record["hilo"] = threading.Thread(target=work, daemon=True, name="kit-ejecutar")
            self._ejecuciones[name] = record
            self._ultima = name
            record["hilo"].start()
        except BaseException:
            self._candado.release()
            raise
        return {"ejecucion": name, "estado": "en_curso"}

    def esperar(self, ejecucion, timeout=60):
        """Para pruebas: espera a que termine la ejecución lanzada."""
        self._ejecuciones[ejecucion]["hilo"].join(timeout)

    # ------------------------------------------------------------------ pantalla 4: resultado

    def resultado(self, ejecucion=None):
        """JSON listo para pintar: franja, contadores, conservación, pestañas y pie, todo desde los archivos del kit."""
        name = ejecucion or self._ultima
        if name is None:
            return self._sin_ejecuciones()
        if not isinstance(name, str) or not NOMBRE_EJECUCION.fullmatch(name):
            raise PeticionInvalida("Nombre de ejecución no admitido")
        folder = self._permitida("results/" + name, ("results",), debe_existir=False)
        record = self._ejecuciones.get(name)
        manifest = _leer_json(folder / "manifiesto.json")
        if manifest is None:
            if record and record["hilo"].is_alive():
                return self._base(name, "en_curso", {"tipo": "curso", "titulo": "Ejecutando…",
                                                     "detalle": "El kit está leyendo la receta y las entradas."})
            if record and record["salida"] is not None:
                return self._desde_cli(name, record)
            raise PeticionInvalida("No existe esa ejecución", 404)
        return self._desde_manifiesto(name, folder, manifest, record)

    def _sin_ejecuciones(self):
        return self._base(None, "sin_ejecuciones", {"tipo": "neutro", "titulo": "Sin ejecuciones todavía",
                                                   "detalle": "Elige un archivo y una receta, y pulsa «Ejecutar»."})

    @staticmethod
    def _base(name, estado, franja, **extra):
        return {"ejecucion": name, "estado": estado, "franja": {"errores": [], **franja}, "contadores": [],
                "conservacion": {"mostrar": False, "motivo": ""}, "pestanas": [],
                "pie": {"original_sin_cambios": False, "carpeta": None, "excel": None}, **extra}

    def _desde_cli(self, name, record):
        """El kit terminó sin crear carpeta: receta inválida, columnas incompatibles u otro error de la CLI."""
        summary = _json_salida(record["salida"]) or {}
        errors = [e for e in summary.get("errores", []) if isinstance(e, dict)]
        title = summary.get("error") or "El kit no pudo ejecutar la receta"
        return self._base(name, "error", {"tipo": "fallo", "titulo": title, "errores": errors,
                                          "detalle": f"Código de salida {record['codigo']}. No se creó ninguna carpeta "
                                                     "de resultados." + (f" Errores: {summary['total_errores']}."
                                                                         if summary.get("total_errores") else "")})

    def _desde_manifiesto(self, name, folder, manifest, record):
        state = manifest.get("estado", "desconocido")
        running = bool(record and record["hilo"].is_alive())
        steps = manifest.get("pasos", [])
        entries = manifest.get("entradas", {})
        issues, warnings = self._totales(folder, steps, entries)
        franja = self._franja(state, manifest, running, issues, warnings)
        result = self._base(name, state, franja, receta=manifest.get("receta", {}).get("nombre"),
                            codigo_salida=manifest.get("codigo_salida"), motivo=manifest.get("motivo"),
                            incidencias=issues, advertencias=warnings, en_marcha=running,
                            pasos=[{"nombre": p["nombre"], "op": p["op"], "estado": p["estado"]} for p in steps])
        split = self._paso_reparto(steps)
        if split is not None:
            result["contadores"], result["conservacion"] = self._contadores(split)
            result["pestanas"] = self._pestanas_tablas(folder, split)
        elif steps and state.startswith("completada"):
            last = next((p for p in reversed(steps) if p.get("salidas") and p["op"] != "exportar"), None)
            if last is not None:
                result["pestanas"] = self._pestanas_tablas(folder, last)
        result["pestanas"].append(self._pestana_incidencias(folder, manifest))
        summary_tab = self._pestana_resumen(folder, steps)
        if summary_tab is not None:
            result["pestanas"].append(summary_tab)
        result["pie"] = self._pie(folder, manifest)
        return result

    def _franja(self, state, manifest, running, issues, warnings):
        kind = TIPO_FRANJA.get(state, "fallo")
        errors = [manifest["error"]] if isinstance(manifest.get("error"), dict) else []
        if state == "en_curso":
            if running:
                return {"tipo": "curso", "titulo": "Ejecutando…", "errores": [],
                        "detalle": "La receta sigue en marcha. Los botones se activarán al terminar."}
            return {"tipo": "fallo", "titulo": "Ejecución cortada de golpe", "errores": [],
                    "detalle": "El manifiesto quedó «en_curso» y nada se está ejecutando: no uses sus resultados."}
        if state == "completada":
            detail = "Todos los pasos terminaron sin incidencias ni advertencias."
            return {"tipo": kind, "titulo": "Completada", "detalle": detail, "errores": errors}
        if state == "completada_con_incidencias":
            detail = (f"Todos los pasos terminaron. Incidencias: {issues}. Advertencias: {warnings}. "
                      "Revisa las filas apartadas antes de usar los resultados.")
            return {"tipo": kind, "titulo": "Completada con incidencias", "detalle": detail, "errores": errors}
        if state == "fallida":
            reason = manifest.get("motivo")
            title = TITULO_FALLO.get(reason, "Fallida")
            detail = f"Motivo: {reason}. No uses resultados parciales (FAILED.json)."
            if reason == "detenida_por_politica" and errors:
                detail = ("Un paso o entrada encontró lo que su política no admite; el flujo se detuvo. "
                          "No uses resultados parciales.")
            return {"tipo": "fallo", "titulo": title, "detalle": detail, "errores": errors}
        return {"tipo": "fallo", "titulo": "Estado desconocido: " + str(state)[:40], "detalle": "", "errores": errors}

    @staticmethod
    def _paso_reparto(steps):
        """El paso que reparte filas: el último con invariante de partición y dos o más salidas."""
        candidates = []
        for step in steps:
            inv = [c for c in step.get("invariantes", []) if c.get("tipo") == "particion"]
            if inv and len(step.get("filas", {}).get("salidas", {})) >= 2:
                candidates.append(step)
        return candidates[-1] if candidates else None

    @staticmethod
    def _contadores(step):
        inv = next(c for c in step["invariantes"] if c.get("tipo") == "particion")
        parts = [(k, v) for k, v in inv.items() if k not in ("tipo", "regla", "cumple", "entrada") and isinstance(v, int)]
        source = step.get("usa", {}).get("entrada") or ", ".join(step.get("usa", {}).get("entradas", []) or [])
        counters = [{"etiqueta": "Entrada" + (f" ({source})" if source else ""), "valor": inv.get("entrada"),
                     "tipo": "neutro", "clave": "entrada"}]
        counters += [{"etiqueta": k.replace("_", " ").capitalize(), "valor": v, "clave": k,
                      "tipo": "rechazo" if k in SEPARATED else "correcto"} for k, v in parts]
        if inv.get("cumple") is True:
            total = inv.get("entrada") or 0
            phrase = " + ".join(str(v) for _, v in parts) + f" = {total}. Ninguna fila se perdió"
            conservation = {"mostrar": True, "frase": phrase, "regla": inv.get("regla"),
                            "partes": [{"nombre": k, "valor": v, "tipo": "rechazo" if k in SEPARATED else "correcto",
                                        "porcentaje": round(v * 100 / total, 1) if total else 0} for k, v in parts]}
        else:
            conservation = {"mostrar": False, "motivo": "El kit no registró la invariante de partición como cumplida "
                                                        f"en el paso {step['nombre']}"}
        return counters, conservation

    def _pestanas_tablas(self, folder, step):
        """Una pestaña por tabla de salida del paso; las apartadas llevan fila original, celdas marcadas y motivos."""
        tabs = []
        carpeta = step.get("carpeta", "")
        issues = (_leer_json(folder / carpeta / "incidencias.json") or {}).get("rows", [])
        by_origin: dict[tuple, list] = {}
        for item in issues:
            by_origin.setdefault((str(item.get("fila")), item.get("origen")), []).append(item)
        for out, info in step.get("salidas", {}).items():
            if out == "incidencias" or "archivo" not in info:
                continue
            table = _leer_json(folder / info["archivo"]) or {"columns": [], "rows": []}
            columns = table.get("columns", [])
            total = info.get("filas", len(table.get("rows", [])))
            provenance = self._procedencia(folder, step, out)
            rows = []
            for index, row in enumerate(table.get("rows", [])[:TOPE_FILAS]):
                origin = provenance.get(str(index + 2), {})
                marks = by_origin.get((origin.get("fila_origen"), origin.get("archivo")), [])
                reasons = []
                for item in marks:
                    text = explicar(item["codigo"], item.get("columna"), item.get("detalle") or None)
                    reasons.append({**text, "columna": item.get("columna"), "detalle": item.get("detalle") or ""})
                rows.append({"fila_original": origin.get("fila_origen"), "entrada": origin.get("entrada"),
                             "celdas": {c: row.get(c) for c in columns},
                             "marcadas": sorted({m["columna"] for m in marks if m.get("columna") in columns}),
                             "motivos": reasons, "motivo_procedencia": origin.get("motivos") or ""})
            tabs.append({"id": out, "titulo": out.replace("_", " ").capitalize(), "conteo": total,
                         "apartadas": out in SEPARATED, "columnas": columns, "filas": rows,
                         "mostradas": len(rows), "total": total, "tope": TOPE_FILAS,
                         "aviso_tope": (f"Mostrando {len(rows)} de {total}. El archivo completo es "
                                        f"{carpeta}/{out}.csv en la carpeta de la ejecución (botón «Abrir carpeta»)."
                                        if total > len(rows) else ""),
                         "validada": info.get("validada", False), "archivo": f"{carpeta}/{out}.csv"})
        return tabs

    @staticmethod
    def _procedencia(folder, step, out):
        """fila de la tabla (encabezado = 1) → {entrada, archivo, fila_origen, motivos}, de *_procedencia.csv."""
        reference = (step.get("trazas") or {}).get(out, "")
        reference = reference.split(" (")[0]
        if not reference.endswith(".csv"):
            return {}
        path = folder / reference
        if not path.is_file():
            return {}
        with path.open(encoding="utf-8", newline="") as stream:
            header = stream.readline().rstrip("\r\n")
        # El delimitador es el de la receta; se reconoce porque el encabezado del archivo es fijo.
        expected = ["fila", "entrada", "archivo", "fila_origen"]
        delimiter = next((d for d in (";", ",", "\t", "|") if header.split(d)[:4] == expected), None)
        if delimiter is None:
            return {}
        return {r["fila"]: r for r in _leer_csv(path, delimiter)}

    @staticmethod
    def _totales(folder, steps, entries):
        """Incidencias y advertencias de la ejecución: las de report.json del kit si existe (ejecución terminada);
        si no, las del manifiesto por entrada y paso, sumadas como hace el resumen de `./kit ejecutar`."""
        report = _leer_json(folder / "report.json")
        if isinstance(report, dict) and isinstance(report.get("incidencias"), int):
            return report["incidencias"], report.get("advertencias", 0)
        records = [*steps, *entries.values()]
        return (sum(r.get("incidencias", 0) for r in records), sum(r.get("advertencias", 0) for r in records))

    def _pestana_incidencias(self, folder, manifest):
        """Incidencias de la ejecución (entradas y pasos, sin las copias de un paso exportar) agrupadas por código.
        La cantidad de cada código es la de `incidencias_por_codigo` del manifiesto; columnas y filas se listan
        desde los `incidencias.json` del kit (hasta TOPE_FILAS por código)."""
        steps = manifest.get("pasos", [])
        exported = {p.get("carpeta") for p in steps if p.get("op") == "exportar"}
        places = [("00-entradas", list(manifest.get("entradas", {}).values()))] + [
            (p["carpeta"], [p]) for p in steps if p.get("carpeta") and p["carpeta"] not in exported]
        groups: dict[str, dict] = {}
        for place, records in places:
            for record in records:
                for code, amount in (record.get("incidencias_por_codigo") or {}).items():
                    group = groups.setdefault(code, {"codigo": code, "cantidad": 0, "columnas": set(), "filas": [],
                                                     "pasos": [], **{k: v for k, v in explicar(code).items()
                                                                     if k in ("etiqueta", "que_paso", "que_hacer",
                                                                              "conocido")}})
                    group["cantidad"] += amount
                    if place not in group["pasos"]:
                        group["pasos"].append(place)
            for item in (_leer_json(folder / place / "incidencias.json") or {}).get("rows", []):
                found = groups.get(item.get("codigo"))
                if found is None:
                    continue
                if item.get("columna"):
                    found["columnas"].add(item["columna"])
                if len(found["filas"]) < TOPE_FILAS:
                    found["filas"].append({"fila": item.get("fila"), "columna": item.get("columna"),
                                           "detalle": item.get("detalle") or "", "origen": Path(item.get("origen") or "").name})
        listed = sorted(groups.values(), key=lambda g: -g["cantidad"])
        for group in listed:
            group["columnas"] = sorted(group["columnas"])
            group["mostradas"] = len(group["filas"])
        total = sum(r.get("incidencias", 0) for _, records in places for r in records)
        return {"id": "incidencias", "titulo": "Incidencias", "conteo": total, "grupos": listed, "tope": TOPE_FILAS}

    def _pestana_resumen(self, folder, steps):
        """La última tabla agregada de un paso transformar (filas en grupos), si la receta la produce."""
        for step in reversed(steps):
            if step.get("op") == "transformar" and "en_grupos" in step.get("filas", {}) and step.get("salidas"):
                info = step["salidas"].get("resultado")
                if not info or "archivo" not in info:
                    return None
                table = _leer_json(folder / info["archivo"]) or {"columns": [], "rows": []}
                rows = table.get("rows", [])[:TOPE_FILAS]
                return {"id": "resumen", "titulo": "Resumen", "conteo": info.get("filas", len(rows)),
                        "columnas": table.get("columns", []), "filas": [{"celdas": r} for r in rows],
                        "mostradas": len(rows), "total": info.get("filas", len(rows)), "tope": TOPE_FILAS,
                        "nota": "Agregado sin procedencia fila a fila (ver el manifiesto del paso " + step["nombre"] + ")",
                        "aviso_tope": (f"Mostrando {len(rows)} de {info.get('filas')}." if info.get("filas", 0) > len(rows)
                                       else "")}
        return None

    def _pie(self, folder, manifest):
        audit = _leer_json(folder / "audit.json") or {}
        excel = None
        for step in manifest.get("pasos", []):
            if step.get("op") != "exportar":
                continue
            for info in step.get("salidas", {}).values():
                for file in info.get("archivos", []):
                    name = file.split("#")[0]
                    if name.endswith(".xlsx") and (folder / name).is_file():
                        excel = name
        return {"original_sin_cambios": audit.get("originales_sha256_sin_cambios") is True,
                "frase_original": "Tu archivo original no se modificó" if audit.get("originales_sha256_sin_cambios") is True
                else "", "carpeta": self._relativa(folder), "excel": excel}

    def abrir(self, ejecucion, archivo=None):
        """Abre la carpeta de la ejecución o un archivo de ella con el explorador del sistema."""
        if not isinstance(ejecucion, str) or not NOMBRE_EJECUCION.fullmatch(ejecucion):
            raise PeticionInvalida("Nombre de ejecución no admitido")
        folder = self._permitida("results/" + ejecucion, ("results",))
        target = folder
        if archivo:
            target = self._permitida("results/" + ejecucion + "/" + str(archivo), ("results",))
            if not target.is_relative_to(folder):
                raise PeticionInvalida("Ruta fuera de la ejecución")
        self.abridor(target)
        return {"abierto": self._relativa(target)}

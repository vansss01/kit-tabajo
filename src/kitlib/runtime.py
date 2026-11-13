import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def configure():
    """Todas las escrituras controladas se restringen al proyecto real."""
    settings = {"TMPDIR": "tmp", "TEMP": "tmp", "TMP": "tmp",
                "XDG_CACHE_HOME": ".cache", "XDG_CONFIG_HOME": ".runtime/config",
                "XDG_DATA_HOME": ".runtime/data", "XDG_STATE_HOME": ".runtime/state",
                "PIP_CACHE_DIR": ".cache/pip", "RUFF_CACHE_DIR": ".cache/ruff",
                "MYPY_CACHE_DIR": ".cache/mypy"}
    for key, relative in settings.items():
        path = inside(ROOT / relative)
        path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    (ROOT / "logs").mkdir(exist_ok=True)  # ignorada por Git: no existe en un clon nuevo
    os.environ.update(PYTHONDONTWRITEBYTECODE="1", PIP_CONFIG_FILE=os.devnull,
                      PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    tempfile.tempdir = str(ROOT / "tmp")
    # Windows redirigido usa cp1252 y falla con «→» o nombres no latinos: salida UTF-8
    # aquí y en los procesos hijos, igual que en Linux.
    os.environ["PYTHONUTF8"] = "1"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


class KitError(ValueError):
    """Error previsto con código estable (codigos.ERRORES), campo afectado y sugerencia."""

    def __init__(self, message, campo=None, sugerencia=None, codigo="argumento_invalido"):
        super().__init__(message)
        self.campo, self.sugerencia, self.codigo = campo, sugerencia, codigo


def error_info(exc):
    """(código, campo, sugerencia) de una excepción, para la salida estructurada."""
    if isinstance(exc, KitError):
        return exc.codigo, exc.campo, exc.sugerencia
    if isinstance(exc, UnicodeError):
        return "codificacion_incorrecta", "--encoding", "Pruebe --encoding cp1252 (Excel en Windows) o utf-8"
    if isinstance(exc, FileNotFoundError):
        return "archivo_no_encontrado", None, "Revise las rutas y las comillas"
    if isinstance(exc, FileExistsError):
        return "salida_existente", "--run-name", "Use otro --run-name; nunca se sobrescribe"
    if isinstance(exc, ValueError) and str(exc).startswith("Clave JSON repetida"):
        return "clave_json_repetida", None, "Cada nombre puede aparecer una sola vez en un mismo objeto"
    if exc.__class__.__name__ == "JSONDecodeError":
        return "json_invalido", None, "Revise la sintaxis del JSON"
    return "error_de_ejecucion", None, None


def public_message(exc, encoding=""):
    """Mensaje de error para terminal y registros: sin traceback ni valores de celdas."""
    if isinstance(exc, UnicodeError):
        return ("El archivo no corresponde a --encoding " + str(encoding)[:30]
                + ". Pruebe --encoding cp1252 (Excel en Windows) o utf-8.")
    if isinstance(exc, FileNotFoundError):
        return "No existe un archivo de entrada, reglas o plan. Revise las rutas y las comillas."
    if isinstance(exc, FileExistsError):
        return "La salida ya existe. Use otro --run-name; no se sobrescribió."
    if type(exc) in (ValueError, KitError):
        return str(exc)[:240]
    return f"{type(exc).__name__}: no se completó la operación. Revise rutas, opciones y esquema de configuración."


def inside(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Las salidas, temporales y cachés deben quedar dentro del proyecto.")
    return path

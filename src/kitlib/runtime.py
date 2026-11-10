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


def inside(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Las salidas, temporales y cachés deben quedar dentro del proyecto.")
    return path

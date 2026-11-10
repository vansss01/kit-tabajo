import os
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
    os.environ.update(PYTHONDONTWRITEBYTECODE="1", PIP_CONFIG_FILE=os.devnull,
                      PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    tempfile.tempdir = str(ROOT / "tmp")


def inside(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Las salidas, temporales y cachés deben quedar dentro del proyecto.")
    return path

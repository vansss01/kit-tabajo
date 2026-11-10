"""Prueba reconstrucción en un entorno nuevo y aislado dentro de tmp/."""
import json
import os
import platform
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kitlib.runtime import configure

configure()
with tempfile.TemporaryDirectory(prefix="reconstruccion sin red-", dir=ROOT / "tmp") as folder:
    environment = Path(folder) / "entorno nuevo"
    venv.EnvBuilder(with_pip=True, symlinks=False).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    with (ROOT / "logs" / "offline.log").open("w", encoding="utf-8") as log:
        subprocess.run([str(python), "-B", "-m", "pip", "install", "--no-compile", "--no-index",
                        "--find-links", str(ROOT / "vendor"), "-r", str(ROOT / "requirements-dev.lock")],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run([str(python), "-B", "-m", "pip", "check"], stdout=log, stderr=subprocess.STDOUT, check=True)
    completed = subprocess.run([str(python), "-B", str(ROOT / "kit.py"), "inspeccionar",
                                str(ROOT / "examples/equipos.csv"), "--delimiter", ";", "--json"],
                               capture_output=True, text=True, check=True, encoding="utf-8")
    summary = json.loads(completed.stdout)
    assert summary["filas_procesadas"] == 3
    versions = subprocess.check_output([str(python), "-B", "-m", "pip", "freeze"], text=True, encoding="utf-8")
    assert versions.strip() == (ROOT / "requirements-dev.lock").read_text(encoding="utf-8").strip()
    record = {"estado": "ok", "sin_indice_de_red": True, "entorno_nuevo": True,
              "plataforma": platform.platform(), "python": sys.version,
              "dependencias": versions.splitlines(), "prueba_cli": summary}
    (ROOT / "logs" / "offline_verificado.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
print("Reconstrucción offline completa, versiones idénticas, pip check y CLI: OK")

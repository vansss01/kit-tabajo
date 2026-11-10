"""Reconstrucción local. Ejecutar: python3 -B scripts/setup.py [--offline] [--dev]."""
import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kitlib.runtime import configure

configure()
p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--offline", action="store_true")
p.add_argument("--dev", action="store_true")
args = p.parse_args()
if sys.version_info < (3, 11):
    raise SystemExit("Se requiere Python 3.11 o posterior")
target = ROOT / (".venv-win" if os.name == "nt" else ".venv")
python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if not python.exists():
    venv.EnvBuilder(with_pip=True, symlinks=False).create(target)
requirements = ROOT / ("requirements-dev.lock" if args.dev else "requirements.txt")
command = [str(python), "-B", "-m", "pip", "install", "--no-compile", "-r", str(requirements)]
if args.offline:
    command += ["--no-index", "--find-links", str(ROOT / "vendor")]
with (ROOT / "logs" / "setup.log").open("a", encoding="utf-8") as log:
    subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
print("Entorno listo:", python)

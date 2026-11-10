"""Descargar ruedas para reconstrucción local; solo contacta el índice de paquetes."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kitlib.runtime import configure

configure()
with (ROOT / "logs" / "download.log").open("a", encoding="utf-8") as log:
    subprocess.run([sys.executable, "-B", "-m", "pip", "download", "--only-binary=:all:",
                    "--dest", str(ROOT / "vendor"), "-r", str(ROOT / "requirements-dev.lock")],
                   cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
manifest = [{"archivo": p.name, "bytes": p.stat().st_size,
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted((ROOT / "vendor").glob("*.whl"))]
(ROOT / "vendor" / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print("Ruedas archivadas:", len(manifest))

"""Lint, tipos y pruebas; registro local y código no cero si algún paso falla."""
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kitlib.runtime import configure

configure()
commands = [("lint", ["-m", "ruff", "check", "src", "kit.py", "scripts", "tests"]),
            ("tipos", ["-m", "mypy"]),
            ("pruebas", ["-m", "unittest", "discover", "-s", "tests", "-v"])]
failed = False
for name, command in commands:
    result = subprocess.run([sys.executable, "-B", *command], cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    (ROOT / "logs" / (name + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
    print(name + ": " + ("OK" if result.returncode == 0 else "FALLO") + " → logs/" + name + ".log")
    if result.returncode:
        print((result.stdout + result.stderr)[-7000:])
        failed = True
raise SystemExit(1 if failed else 0)

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
]


def run(selected):
    configure()  # crea tmp/ dentro del proyecto si falta
    missing = undetected = 0
    for name, path, old, new, tests in selected:
        with tempfile.TemporaryDirectory(prefix="mutante-", dir=ROOT / "tmp") as folder:
            copy = Path(folder)
            for item in ("src", "tests", "recetas", "examples", "kit.py", "pyproject.toml"):
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

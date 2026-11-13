"""Regenera desde el código los artefactos del contrato: schemas/*.schema.json (src/kitlib/esquemas.py)
y docs/CODIGOS.md (src/kitlib/codigos.py). Uso: `python -B scripts/esquemas.py`.
Las pruebas fallan si los publicados no coinciden con lo generado."""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kitlib.codigos import codigos_md
from kitlib.esquemas import esquemas


def text(schema):
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    folder = ROOT / "schemas"
    folder.mkdir(exist_ok=True)
    for name, schema in esquemas().items():
        (folder / f"{name}.schema.json").write_text(text(schema), encoding="utf-8", newline="\n")
        print(f"schemas/{name}.schema.json")
    (ROOT / "docs" / "CODIGOS.md").write_text(codigos_md(), encoding="utf-8", newline="\n")
    print("docs/CODIGOS.md")

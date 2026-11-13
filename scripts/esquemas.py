"""Regenera schemas/*.schema.json desde el código (src/kitlib/esquemas.py).
Uso: `python -B scripts/esquemas.py`. La prueba test_esquemas falla si los publicados no coinciden."""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kitlib.esquemas import esquemas


def text(schema):
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    folder = ROOT / "schemas"
    folder.mkdir(exist_ok=True)
    for name, schema in esquemas().items():
        (folder / f"{name}.schema.json").write_text(text(schema), encoding="utf-8", newline="\n")
        print(f"schemas/{name}.schema.json")

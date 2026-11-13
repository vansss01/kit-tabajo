"""scripts/medir.py: el conjunto generado tiene las proporciones anunciadas en MEDICIONES.md (hallazgo 4 de la
auditoría 1.5.0: el 1 % de filas modificadas salía en 0 porque se aplicaba a filas ya excluidas). Esperados a mano."""
import csv
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
_spec = importlib.util.spec_from_file_location("medir", ROOT / "scripts" / "medir.py")
assert _spec is not None and _spec.loader is not None
medir = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(medir)


class MedirTests(unittest.TestCase):
    def test_generated_set_has_the_announced_proportions(self):
        with tempfile.TemporaryDirectory(prefix="medir-", dir=ROOT / "tmp") as folder:
            datos = Path(folder) / "datos"
            medir.generar(datos, 1000, 2026)
            # 1000 filas: 2 % nuevas = 20 (múltiplos de 50 ausentes en anterior), 0 eliminadas, 1 % modificadas = 10
            # (filas 25, 125, …, 925 con horas 1,0 en anterior) y 1 fuera de rango (fila 1000, horas 25,0).
            expected = {"filas": 1000, "nuevas": 20, "eliminadas": 0, "modificadas": 10, "fuera_de_rango": 1}
            self.assertEqual(medir.proporciones(datos), expected)
            self.assertEqual(medir.comprobar_proporciones(datos, 1000), expected)
            with (datos / "anterior.csv").open(encoding="utf-8", newline="") as stream:
                antes = {r["orden"]: r for r in csv.DictReader(stream, delimiter=";")}
            with (datos / "ordenes.csv").open(encoding="utf-8", newline="") as stream:
                despues = {r["orden"]: r for r in csv.DictReader(stream, delimiter=";")}
            self.assertEqual(antes["OT0000025"]["horas"], "1,0")
            self.assertNotEqual(despues["OT0000025"]["horas"], "1,0")
            # Toda fila marcada como modificada difiere de verdad, aunque sus horas originales fueran 1,0.
            self.assertTrue(all(antes[k]["horas"] != despues[k]["horas"] for k in antes if int(k[2:]) % 100 == 25))
            self.assertNotIn("OT0000050", antes)
            self.assertNotIn("OT0000100", antes)  # múltiplo de 50: excluida; en 1.5.0 era además la «modificada» imposible
            self.assertEqual(antes["OT0000075"], despues["OT0000075"])  # ni excluida ni modificada: idéntica
            # El conjunto de 1.5.0 (sin modificadas) debe rechazarse.
            roto = Path(folder) / "roto"
            shutil.copytree(datos, roto)
            lines = (roto / "ordenes.csv").read_text(encoding="utf-8").splitlines()
            (roto / "anterior.csv").write_text("\n".join([lines[0]] + [ln for n, ln in enumerate(lines[1:], 1) if n % 50]) + "\n",
                                               encoding="utf-8")
            self.assertEqual(medir.proporciones(roto)["modificadas"], 0)
            with self.assertRaises(SystemExit):
                medir.comprobar_proporciones(roto, 1000)


if __name__ == "__main__":
    unittest.main()

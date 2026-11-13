"""Los comandos `./kit` de docs/REPORTE_KIT.html se ejecutan y su código de salida se compara con el que el texto
del reporte indica o da a entender (hallazgo 2 de la auditoría 1.5.0: el ejemplo SQL producía sumas NULL y código 1
mientras el reporte mostraba totales). Los códigos esperados están escritos a mano a partir de la prosa del reporte.

Límite declarado: solo este archivo. Los manuales de docs/tools, EJERCICIOS.md y APRENDER.md traen comandos con rutas
genéricas (ARCHIVO, NOMBRE) y fragmentos; extender esta prueba a todos sería desproporcionado. Un comando nuevo en el
reporte sin código esperado aquí hace fallar la prueba a propósito."""
import html
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kitlib.runtime import configure

configure()
REPORTE = ROOT / "docs" / "REPORTE_KIT.html"
CON_SALIDA = {"inspeccionar", "comparar", "consolidar", "validar", "transformar", "exportar", "consultar", "ejecutar"}
# Comando tal como aparece tras `./kit ` (continuaciones con \\ unidas) → código que el reporte da a entender.
ESPERADOS = {
    "inspeccionar examples/equipos.csv --delimiter ';'": 0,
    "validar 'examples/con incidencias.csv' --delimiter ';' --rules examples/reglas.json": 1,  # «1 válida, 2 inválidas, 6 incidencias»
    "comparar examples/anterior.csv 'examples/entradas/turno A.csv' --delimiter ';' --key orden": 0,
    "consolidar examples/entradas --delimiter ';'": 0,
    "transformar 'examples/entradas/turno A.csv' --delimiter ';' --decimal ',' --plan examples/plan.json": 0,
    "exportar 'examples/con incidencias.csv' --delimiter ';' --rules examples/reglas.json": 1,  # válidos e inválidos
    "consultar examples/minera/ordenes.csv --delimiter ';' --decimal ',' --tipo t.horas=number "
    "--sql \"SELECT estado, COUNT(*) AS n, SUM(horas) AS horas FROM t GROUP BY estado\"": 0,  # muestra totales, no NULL
    "ejecutar examples/recetas/ordenes_semana_1.csv --receta recetas/revision_ordenes.json --vista-previa": 0,
    "ejecutar examples/recetas/ordenes_semana_1.csv --receta recetas/revision_ordenes.json": 1,  # 7 rechazadas
    "comprobar recetas/consolidacion_turnos.json": 0,
    "catalogo": 0,
    "limpiar": 0,  # sin --apply solo lista
}
OMITIDOS = {  # prefijo → motivo por el que no se ejecuta
    "resultados": "depende de las ejecuciones reales en results/ y NOMBRE es un marcador",
    "bitacora": "escribe en data/bitacora (diario privado)",
}


def comandos(texto):
    found = []
    for block in re.findall(r"<pre><code>(.*?)</code></pre>", texto, re.DOTALL):
        joined = html.unescape(block).replace("\\\n", " ")
        for line in joined.splitlines():
            line = line.strip()
            if line.startswith("./kit "):
                line = line.split(" | ")[0].split(" #")[0].strip()
                found.append(" ".join(line[len("./kit "):].split()))
    return found


class ReporteTests(unittest.TestCase):
    def test_every_kit_command_in_the_report_exits_as_the_report_says(self):
        found = comandos(REPORTE.read_text(encoding="utf-8"))
        self.assertTrue(found)
        to_run = [c for c in found if not any(c.split()[0] == k for k in OMITIDOS)]
        self.assertEqual(sorted(set(to_run)), sorted(ESPERADOS), "declare el código esperado de cada comando del reporte")
        with tempfile.TemporaryDirectory(prefix="reporte-", dir=ROOT / "tmp") as folder:
            for command in to_run:
                with self.subTest(command=command):
                    tokens = shlex.split(command)
                    if tokens[0] in CON_SALIDA:
                        tokens += ["--output", folder]
                    result = subprocess.run([sys.executable, "-B", str(ROOT / "kit.py"), *tokens], cwd=ROOT,
                                            capture_output=True, text=True, encoding="utf-8")
                    self.assertEqual(result.returncode, ESPERADOS[command], result.stdout[-1500:] + result.stderr[-500:])
                    if tokens[0] == "consultar":  # el reporte muestra sumas: ningún valor pudo quedar NULL
                        self.assertNotIn("valores_no_numericos_cargados_como_null", result.stdout)


if __name__ == "__main__":
    unittest.main()

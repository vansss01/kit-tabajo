# Índice compacto

Desde la raíz con el entorno activado. Ayuda: `python -B kit.py COMANDO --help`.
Opciones comunes: `--delimiter`, `--encoding`, `--decimal`, `--date-format`, `--sheet`,
`--output`, `--run-name`, `--json`, `--verbose`. Códigos 0/1/2: éxito/incidencias/error.

| Comando / propósito | Implementación | Opciones principales | Manual |
|---|---|---|---|
| inspeccionar: perfilar sin modificar | operations.py:inspect_table | --sample 0..20, --limit N | [inspección](tools/inspeccionar.md) |
| comparar: altas/bajas/campos | operations.py:compare | segundo archivo, --key A B, --after-sheet | [comparación](tools/comparar.md) |
| consolidar: unir con procedencia | cli.py:consolidate | carpeta, --glob, --recursive, --exclude | [consolidación](tools/consolidar.md) |
| validar: reglas sin corregir | operations.py:validate | --rules JSON | [validación](tools/validar.md) |
| transformar: plan declarativo | operations.py:transform | --plan JSON | [transformación](tools/transformar.md) |
| exportar: CSV/JSON/Excel | tableio.py; cli.py:execute | --rules opcional, --format, --safe-csv | [exportación](tools/exportar.md) |

Los módulos están en `src/kitlib/`. Ejemplos pequeños:

```bash
python -B kit.py inspeccionar examples/equipos.csv --delimiter ';' --sample 2
python -B kit.py comparar examples/anterior.csv 'examples/entradas/turno A.csv' --delimiter ';' --key orden
python -B kit.py consolidar examples/entradas --delimiter ';'
python -B kit.py validar 'examples/con incidencias.csv' --delimiter ';' --rules examples/reglas.json
python -B kit.py transformar 'examples/entradas/turno A.csv' --delimiter ';' --plan examples/plan.json
python -B kit.py exportar 'examples/con incidencias.csv' --delimiter ';' --rules examples/reglas.json
```

Flujo comprobado con aserciones: `python -B scripts/demo.py`.
Verificación completa: `python -B scripts/check.py`.

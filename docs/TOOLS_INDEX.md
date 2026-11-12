# Índice compacto

Desde la raíz: `./kit COMANDO` (Linux) o `kit COMANDO` (Windows); equivale a
`python -B kit.py COMANDO` con el entorno activado. Ayuda: `./kit COMANDO --help`.
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
| consultar: SQL solo lectura | operations.py:query | --sql, --tabla N=ARCHIVO, --numeric, --show | [consulta](tools/consultar.md) |
| ejecutar: receta de pasos con trazabilidad | recetas.py, traza.py | --receta JSON, --entrada N=ARCHIVO, --vista-previa | [recetas](tools/ejecutar.md) |
| bitacora: diario e informe | bitacora.py | texto, --horas, --etiqueta, --ver, --informe | [bitácora](tools/bitacora.md) |
| limpiar: ejecuciones antiguas | cli.py:clean | --keep N, --apply (sin él no borra) | [limpieza](tools/limpiar.md) |

El resumen `--json` ya trae `incidencias_por_codigo`, `advertencias_por_codigo`, `conteos` y,
al inspeccionar, `tablas` (columnas por hoja). Abrir `report.json` solo si falta la fila exacta.
Con `posible_delimitador_incorrecto` el resumen trae `sugerencia` con la opción a repetir.
Si el error menciona `--encoding`, el archivo suele ser `cp1252` (Excel en Windows).

Los módulos están en `src/kitlib/`. Ejemplos pequeños:

```bash
python -B kit.py inspeccionar examples/equipos.csv --delimiter ';' --sample 2
python -B kit.py comparar examples/anterior.csv 'examples/entradas/turno A.csv' --delimiter ';' --key orden
python -B kit.py consolidar examples/entradas --delimiter ';'
python -B kit.py validar 'examples/con incidencias.csv' --delimiter ';' --rules examples/reglas.json
python -B kit.py transformar 'examples/entradas/turno A.csv' --delimiter ';' --plan examples/plan.json
python -B kit.py exportar 'examples/con incidencias.csv' --delimiter ';' --rules examples/reglas.json
```

Tablas grandes: `exportar --format csv` evita el XLSX, que es lo más lento.
Datos mineros ficticios y ejercicios con respuesta: `examples/minera/`, `docs/EJERCICIOS.md`
(material de estudio; no hace falta leerlo para trabajar). `consultar` muestra valores de
celdas en la terminal: con datos sensibles usar `--show 0` (los archivos siguen conteniéndolos).
Para calcular con SQL declarar `--numeric`; sin él puede avisar `resultado_depende_de_texto_sin_numeric`.
Sumas exactas al dígito: `transformar`. Límites numéricos: manual de consulta.
Flujo comprobado con aserciones: `python -B scripts/demo.py`.
Verificación completa: `python -B scripts/check.py`.

# Resultados (leer una ejecución sin abrir carpetas)

```bash
./kit resultados                                   # resumen de la ejecución más reciente
./kit resultados 20261113T…-ejecutar-ab12 --json   # una ejecución concreta (nombre o ruta)
./kit resultados NOMBRE --paso revision             # detalle de un paso de receta
./kit resultados NOMBRE --incidencias valor_no_unico --n 5
```

- **Resumen**: estado, código de salida, si está completa (`report.json`) o fallida
  (`FAILED.json`), conteos por código y, en recetas, el estado y las filas de cada paso. Si la
  ejecución está incompleta o `en_curso`, lo avisa: no uses sus resultados.
- **`--paso`** (solo recetas): estado, conteos de filas, invariantes, archivos de traza, salidas,
  política y error del paso, leídos de `manifiesto.json`.
- **`--incidencias CODIGO`**: las primeras N incidencias o advertencias con ese código (fila,
  columna, archivo de origen, paso); `--n` 10 por defecto y como máximo **100**, aunque se pida más
  (`limite` y `total` lo indican). Un código desconocido es error con sugerencia.

Nunca muestra valores de celdas: solo códigos, conteos, números de fila, nombres de columna y rutas.
`--output` indica otra carpeta de ejecuciones dentro del proyecto. Errores con código estable
(`ejecucion_no_encontrada`, `argumento_invalido`); `--json` para salida estructurada.

# Inspeccionar

```bash
python -B kit.py inspeccionar 'examples/entradas/turno A.csv' --delimiter ';' --decimal ',' --sample 2 --json
python -B kit.py inspeccionar examples/equipos.csv --delimiter ';' --limit 2 --sample 0 --verbose
```

`--sample 0..20` limita los valores de muestra guardados (3 por defecto). `--limit N`
limita el análisis, no solo la salida. Sin límite el análisis es completo. `--sheet`
selecciona una hoja; por defecto Excel inspecciona todas y lista sus nombres.

`report.json → detalle.analisis` contiene columnas, frecuencias de tipos inferidos,
nulos/vacíos, filas analizadas, filas estructuralmente válidas y duplicados adicionales.
Muestras se guardan en el informe y solo se muestran con `--verbose`. Terminal limita
hojas, columnas, listas y longitud de textos; el informe conserva el detalle solicitado.

Los conteos son exactos dentro del alcance. Si faltan filas por leer, total=null;
no se presentan estimaciones. Encabezado inválido no permite contar sus filas.
Vacíos, estructura irregular y limitaciones de Excel se señalan sin editar el archivo.

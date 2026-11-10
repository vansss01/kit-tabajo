# Exportar

```bash
python -B kit.py exportar 'examples/con incidencias.csv' --delimiter ';' --rules examples/reglas.json
```

`--format all` (predeterminado), xlsx, csv o json. `--rules` aplica la misma validación
sin corrección; sin reglas solo separa errores estructurales y lo declara en el informe.
Genera hojas/archivos validos, invalidos, incidencias y resumen. XLSX tiene encabezados
con estilo, filtros, fila superior congelada y anchos entre 12 y 48 caracteres,
estimados con las primeras 100 filas. Reporte y auditoría JSON siempre están presentes.

XLSX escribe todo como texto para preservar códigos, precisión y fórmulas inertes.
No conserva el libro original, macros ni formato. CSV usa UTF-8 y el delimitador
seleccionado; JSON conserva null frente a cadena vacía y sirve para encadenar comandos.

`--safe-csv` es una transformación explícita de exportación: añade apóstrofo a textos
potencialmente interpretados como fórmulas por hojas de cálculo. `report.json` cuenta
celdas alteradas. Sin esta opción CSV conserva fielmente los valores; importa códigos
como texto cuando lo abras en Excel. XLSX y JSON no se alteran por `--safe-csv`.

Siempre se crea una carpeta exclusiva, nunca se reemplazan archivos existentes.
Si la exportación falla, descarta sus archivos parciales marcados FAILED.

# Consolidar

```bash
python -B kit.py consolidar examples/entradas --delimiter ';'
```

Lee `*.csv` por defecto. `--glob '*.xlsx'` cambia el patrón; `--recursive` recorre
subcarpetas y `--exclude 'archivo.csv'` o un patrón relativo excluye archivos concretos.
Selecciona en orden de ruta. El primer archivo legible con encabezado válido establece
el conjunto de columnas. Se permite distinto orden, no columnas adicionales/ausentes.

Añade `__archivo_origen` (ruta absoluta resuelta) y `__fila_origen` (registro lógico,
encabezado=1). Esos nombres están reservados. Un archivo incompatible o mal formado
se rechaza completo: el informe enumera faltantes/adicionales, aceptados y rechazados.
No suprime duplicados. Los vacíos generan incidencias y las tablas solo con encabezados
una advertencia. Un archivo ilegible no impide procesar otros compatibles.

Se excluyen automáticamente la raíz de salida elegida, `results/`, directorios internos
de entorno/cachés/temporales y cualquier archivo bajo un directorio `.kit-output`.
Conserva esa marca si mueves resultados. El informe lista las exclusiones. Esto evita
incorporar salidas anteriores incluso al cambiar `--output` entre ejecuciones. Un CSV
exportado y copiado a una carpeta sin marca será una entrada normal: usa `--exclude`.

Código 1 significa que debes revisar rechazos/advertencias aunque existan filas útiles.
`filas_analizadas` suma registros leídos de archivos estructuralmente analizables,
incluso de archivos rechazados; `filas_salida` cuenta solo filas aceptadas.

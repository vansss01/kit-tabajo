# Comparar

```bash
python -B kit.py comparar examples/anterior.csv 'examples/entradas/turno A.csv' --delimiter ';' --key orden
```

Orden de argumentos: tabla anterior, tabla posterior. `--key orden equipo` permite clave
compuesta. `--sheet` elige hoja anterior; `--after-sheet` permite un nombre distinto en
el segundo libro. Las demás opciones de lectura son compartidas entre entradas: si
usan convenciones distintas, prepara copias explícitamente antes de compararlas.

Ambas tablas deben tener el mismo conjunto de columnas; su orden puede diferir.
Claves inexistentes son error de configuración. Claves vacías/duplicadas, problemas
estructurales o conjuntos de columnas distintos bloquean toda la comparación.

Salidas: nuevos, eliminados y cambios. Cambios tiene `clave` (objeto JSON en texto),
`campo`, `antes`, `despues`, una fila por campo cambiado. El informe distingue registros
modificados de campos cambiados. Comparación exacta de texto, sin recortar espacios,
normalizar números ni convertir fechas. `0007` y `7` son claves diferentes.

Comprobación: anterior = eliminados + modificados + sin cambios;
posterior = nuevos + modificados + sin cambios. La demo verifica ambos conteos.

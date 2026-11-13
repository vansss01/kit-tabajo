# Formatos, integridad y límites

## Lectura

- CSV usa `csv.reader`, encabezado obligatorio, delimitador explícito (coma por defecto,
  `--delimiter TAB` para tabulación), UTF-8 con BOM opcional. `--encoding cp1252` es una
  alternativa explícita. No se prueba una codificación distinta silenciosamente.
- Celdas se conservan como texto; ausencia de Excel/JSON se representa por null.
  Vacío para reglas significa null, cadena vacía o solo espacios. No se recortan valores.
- Encabezados vacíos/duplicados producen incidencias. Filas de ancho incorrecto se
  registran y no se fuerzan a la estructura. Las validaciones/exportaciones pueden
  conservar otras filas; consolidación rechaza el archivo completo si tiene estos errores.
- Fila es el número de **registro lógico**, encabezado=1. Un CSV con saltos de línea
  dentro de comillas puede ocupar varias líneas físicas. La procedencia usa ese número.
- Inferencia solo describe valores observados. No determina el tipo de almacenamiento.
  Las cadenas de enteros con ceros iniciales se señalan como `codigo_texto`.
- Inspector completo cuenta el alcance íntegro; `--limit N` recorre las primeras N filas
  y comprueba si hay otra. Si hay más, `filas_totales=null`, `alcance=muestra_inicial`.
  No hace muestreo aleatorio ni extrapola. Encabezado inválido: alcance no analizable,
  total desconocido. Duplicados son filas idénticas adicionales a la primera, sin
  normalizar texto; todas las estadísticas se refieren al alcance leído.
- El cálculo SHA-256 sí lee todos los bytes incluso si se inspecciona una muestra.
- Tabla JSON admitida: `{"columns":["id"],"rows":[{"id":"0007"}]}`. Solo celdas escalares
  y exactamente las columnas declaradas. Los JSON de informe/configuración no son tablas.

## Excel

XLSX y XLSM se leen en modo de solo lectura, sin ejecutar macros, fórmulas ni vínculos.
El inspector enumera todas las hojas; las otras herramientas exigen `--sheet` si hay
más de una. `.xls`, `.xlsb`, ODS y libros cifrados no se admiten.

Las fórmulas se devuelven como texto, con advertencia; no se usan resultados almacenados
ni se calculan. Las celdas con errores Excel generan advertencia. Un número con formato
simple `0000` genera advertencia de ceros no recuperados. No se detectan todos los
formatos personalizados ni se pueden recuperar dígitos perdidos por Excel.

Fechas nativas se leen como ISO; si openpyxl devuelve un datetime, conserva la hora.
Para validar una cadena `2026-10-01T00:00:00` como fecha usa explícitamente
`date_format: "%Y-%m-%dT%H:%M:%S"`. Una conversión de ese tipo a date descarta la hora
solo cuando el usuario la solicita. No hay manejo automático de husos horarios.

Exportar genera un libro nuevo: no conserva macros, fórmulas ejecutables, formatos,
objetos, gráficos, comentarios ni validaciones del original. Exporta todas las celdas
como texto para preservar códigos y precisión. Los cálculos ya están hechos en Python;
para fórmulas numéricas posteriores en Excel puede ser necesario convertir columnas.
Se rechazan celdas de más de 32767 caracteres y tablas fuera de los límites XLSX,
en vez de truncarlas. Los caracteres XML inválidos pueden causar error de ejecución.

Documentación de referencia de openpyxl:
[lectura y escritura](https://openpyxl.readthedocs.io/en/stable/tutorial.html),
[modo de solo lectura](https://openpyxl.readthedocs.io/en/stable/optimized.html).

## Números, fechas, comparación y transformación

Los números usan Decimal, sin miles ni exponentes. Punto o coma decimal son configurables.
Suma usa precisión ampliada para evitar redondeo de dígitos; media usa la precisión
Decimal predeterminada de 28 dígitos (puede redondear decimales periódicos).
Los resultados numéricos se guardan como cadenas decimales con punto, sin pérdida por
float/JSON/Excel. Tras convertir una columna a número, pasos posteriores deben indicar
`decimal: "."` si la entrada original usaba coma. No se adivinan convenciones mixtas.

Excepción: `consultar` calcula con SQLite REAL (punto flotante, 15–17 cifras significativas), no
con Decimal. Su salida mantiene el mismo contrato de texto decimal con punto y sin exponente,
sin redondeo añadido por el kit, pero los cálculos SQL no son exactos al dígito: para sumas
exactas usar `transformar`. Infinitos y entradas no nulas que quedarían en cero son error
(código 2, sin tabla publicada); una celda vacía es NULL y un texto no numérico es NULL con
advertencia. Detalle y protección ante la omisión de `--numeric`: `tools/consultar.md`.

Fechas requieren representación exacta del formato indicado; por defecto `%Y-%m-%d`.
`03/04/2026` no es una fecha ISO válida. No se interpreta automáticamente como DMY/MDY.
La validación interpreta sin modificar. La comparación es textual exacta: `2,0` y `2,00`
son distintos. Para comparar semánticamente, transforma explícitamente copias antes.
Claves vacías o repetidas bloquean toda la comparación. No se elige una fila al azar.

Una transformación con conversión/filtro numérico inválido falla completa con código 2,
sin publicar una tabla transformada parcial. No existe `eval`, expresiones de Python,
SQL, scripts, importaciones ni filtros ejecutables en los planes. El único SQL es el de
`consultar`: una sentencia de solo lectura sobre una copia en memoria.

## Salidas, registros y privacidad

Las salidas usan creación exclusiva y directorios únicos. Nunca hay opción de sobrescribir.
Si falla una escritura, la carpeta queda marcada `FAILED.json`: no es una transacción
atómica y puede contener archivos parciales. El usuario puede conservarla para diagnóstico.
Si se interrumpe el proceso abruptamente antes de esa marca, la ausencia de `audit.json`
y `report.json` también significa ejecución incompleta.

CSV usa UTF-8 y el delimitador elegido. null y cadena vacía se representan ambos como
campo vacío: para conservar esa distinción usa JSON. CSV no expresa tipos, por lo que
Excel puede interpretar automáticamente `0007` como 7: importa esas columnas como texto
o usa el XLSX del kit. El CSV fiel puede contener textos que otras aplicaciones interpreten
como fórmulas. `exportar --safe-csv` añade apóstrofo explícitamente a textos cuyo primer
carácter no blanco es `=`, `+`, `-` o `@`, incluidos encabezados; el informe cuenta las
celdas alteradas. No afecta JSON/XLSX. No se neutraliza silenciosamente el CSV.

`audit.json` y `logs/*.json` guardan parámetros, versión del kit/Python, rutas, tamaños,
hashes, conteos y comprobación de entradas antes/después. Las configuraciones se
identifican por ruta y hash; no se copian sus posibles valores sensibles al registro.
Para reproducir, conserva las entradas y configuraciones originales y verifica sus hashes.
Versiona código y reglas de ejemplo, no datos reales. Los detalles/muestras/diferencias
sí contienen datos y requieren el cuidado habitual del usuario; en recetas también
`excluidas.csv` y `cambios_celdas.csv` (valores anteriores y nuevos) y las rutas de archivo
de los `*_procedencia.csv`. En recetas `inspeccionar` no incluye muestras salvo `sample`.

### Qué salidas pueden contener valores de celdas

| Salida | ¿Valores? | Cómo ocultarlos |
|---|---|---|
| Terminal y `--json` de `consultar` (`resultado`, hasta `--show` filas, 20 por defecto) | Sí | `--ocultar-valores` o `--show 0` |
| `report.json` de `inspeccionar` (`muestra`, `--sample` 3 por defecto) y su `--verbose` | Sí | `--ocultar-valores` o `--sample 0` |
| `report.json` de un paso `inspeccionar` de receta con `sample` > 0 | Sí | `ejecutar --ocultar-valores` (fuerza 0) |
| `bitacora --ver` | Tus propias notas | No usar `--ver` |
| Resto de terminal, `--json`, `report.json`, `audit.json`, `manifiesto.json`, `resultados`, `comprobar`, `catalogo` | No: códigos, conteos, filas, columnas, rutas | — |
| Archivos de datos: `validos`, `invalidos`, tablas de pasos, `excluidas`, `cambios_celdas`, `cambios` de comparar, exportes | Sí, por naturaleza | No compartirlos; `--ocultar-valores` no los cambia |

`--ocultar-valores` existe en todos los comandos de tablas y en `ejecutar`; donde no hay nada que
ocultar no cambia nada. Sin la opción el comportamiento es el de siempre. Una prueba con valores
centinela únicos comprueba que, con la opción, ninguno llega a la terminal ni a esos resúmenes.

Las operaciones completas y exportaciones mantienen datos en RAM. JSON se carga completo
incluso con `--limit`. CSV/XLSX limitan filas cargadas al inspeccionar con límite, pero no
hay límite de bytes por celda ni defensa completa ante archivos hostiles o bombas ZIP.
defusedxml protege el parseo XML soportado por openpyxl; esto no es un sandbox de archivos.
No hay benchmark de gran escala ni garantías de uso simultáneo de archivos que otros
procesos estén editando; las huellas detectan cambios persistentes durante la ejecución.

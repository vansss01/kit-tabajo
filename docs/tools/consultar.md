# Consultar (SQL)

```bash
./kit consultar examples/minera/ordenes.csv --delimiter ';' \
  --sql "SELECT estado, COUNT(*) AS n FROM t GROUP BY estado ORDER BY n DESC"
./kit consultar examples/minera/detenciones.csv --delimiter ';' --decimal ',' --numeric horas \
  --tabla flota=examples/minera/flota.csv \
  --sql "SELECT f.tipo, ROUND(SUM(t.horas),1) AS horas FROM t JOIN flota f ON f.equipo=t.equipo GROUP BY f.tipo"
```

Carga las tablas en una base SQLite en memoria y ejecuta **una** consulta `SELECT` (o `WITH`).
La entrada se llama `t` (`--name` la renombra); `--tabla NOMBRE=ARCHIVO` agrega otras para `JOIN`.

- Todas las columnas son texto, igual que en el resto del kit: `'0007'` conserva sus ceros y
  `'10' < '9'` como texto. Para sumar, promediar, comparar u ordenar numéricamente **declara el tipo**:
  - `--tipo TABLA.COLUMNA=number` (o `=string`), repetible: solo esa columna de esa tabla. Es lo
    recomendado con varias tablas: `--tipo t.horas=number` no toca `flota.horas` si allí es un código.
  - `--numeric col1 col2` (como siempre): esas columnas en **todas** las tablas que las tengan.
  - En recetas: `"tipos": {"t": {"horas": "number"}, "flota": {"codigo": "string"}}`.
  Los números se leen con `--decimal`. Nunca se convierten columnas sin declararlas (identificadores y
  ceros iniciales intactos). Una celda vacía queda `NULL` sin aviso; un texto no numérico queda `NULL`
  con `valores_no_numericos_cargados_como_null` (código 1). Una columna declarada número y texto a
  la vez, o una columna o tabla inexistente en `--tipo`, es error (código 2).
- Columnas con espacios o tildes van entre comillas dobles: `SELECT "año" FROM t`.
- No se permite modificar, crear, adjuntar ni varias sentencias: responde error (código 2).

`--show N` (20; 0–100) muestra las primeras filas en la terminal: **son valores de celdas**, también
con `--json`. `--show 0` solo las oculta de la terminal: el resultado completo sigue guardado en
`validos.csv` y `validos.json`, que requieren el mismo cuidado. `--ocultar-valores` equivale a `--show 0`.

## Números: qué es exacto y qué no

- **Salida.** Los números del resultado se guardan como texto decimal con punto y sin exponente
  (`1234567890123`, `0.0000001`, `6`), con los dígitos justos para recuperar el mismo valor: el kit
  no añade redondeo. Sirven de entrada a `validar` y `transformar` con `--decimal .`
  (el predeterminado). Excepción: si la propia consulta convierte un número a texto
  (`CAST(x AS TEXT)`, `x || ''`), el texto lo produce SQLite y puede traer exponente.
- **Precisión.** `--numeric` usa números de punto flotante (SQLite REAL): unas 15–17 cifras
  significativas. Un valor con más cifras se redondea al cargarlo y se avisa con
  `numeros_redondeados_por_precision_real` (código 1). Los cálculos (`SUM`, `AVG`, `*`, `/`) pueden
  acumular error en las últimas cifras sin aviso: `0.1 + 0.2` da `0.30000000000000004`. Usa `ROUND`
  para informar, y `transformar` (op `group`, Decimal) cuando la suma deba ser exacta al dígito.
- **Rango.** Un valor de `--numeric` demasiado grande (infinito) o tan pequeño que quedaría en cero,
  o un resultado infinito, es un error (código 2): el mensaje nombra tabla y columna sin mostrar
  celdas, no se publica ninguna tabla y la carpeta queda con `FAILED.json`. No se detecta un
  *resultado calculado* que se vuelve cero por ser demasiado pequeño (p. ej. `1e-200 * 1e-200`).
- **Detector de texto numérico** (cuando falta el tipo). Sobre texto SQLite calcula mal sin avisar:
  `SUM` de `2,5` y `3,5` da 5, `'10,5' < '9,5'` y `v > 3` compara letras. Si la consulta lee una
  columna **sin tipo declarado** cuyos valores son en su mayoría números y alguno tiene decimales (sin
  códigos con ceros iniciales), el kit repite la consulta en memoria con esa columna como número; si
  el resultado cambia, publica el resultado como texto con la advertencia
  `resultado_depende_de_texto_sin_numeric` (código 1) y la sugerencia de declararla.
  - **No es una validación del SQL**: es una comparación heurística de dos ejecuciones. No avisa por
    columnas solo de enteros (su `SUM` es correcto, pero orden, `MAX` y comparaciones siguen siendo
    de texto) ni con mayoría de valores no numéricos. Falsos positivos: tratar a propósito como texto
    una columna con decimales (`LENGTH(v)`, `v || ' h'`), funciones aleatorias, u orden distinto de
    filas sin `ORDER BY` (declara `=string` para silenciarlo a sabiendas).
  - **Coste acotado**: la repetición duplica tiempo y memoria. Solo se hace si el total de filas de
    todas las tablas de la consulta no supera `--detector-max-filas` (200 000 por defecto; en recetas
    `detector_max_filas`). Por encima no se repite y se avisa `detector_texto_numerico_omitido`
    (código 1): declara los tipos. Es un límite de filas, no de tiempo, para que el resultado sea
    siempre el mismo.
  - **Configurable**: `--detector-texto-numerico no` (recetas: `"detector": false`) lo apaga; es una
    decisión explícita y no se avisa. Las columnas con tipo declarado nunca se revisan.
  - Para el caso `2,5 + 3,5` la alternativa clara es declarar el tipo: `--tipo t.v=number` da 6.
- **Exactitud.** SQLite REAL no es decimal exacto. Para sumas o medias exactas al dígito usa
  `transformar` (op `group`, aritmética Decimal).

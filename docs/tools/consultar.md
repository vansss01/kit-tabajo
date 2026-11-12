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
  `'10' < '9'` como texto. Para sumar, promediar, comparar u ordenar numéricamente **declara las
  columnas con `--numeric col1 col2`**; se interpretan con `--decimal`. Una celda vacía queda `NULL`
  sin aviso; un texto no numérico queda `NULL` con `valores_no_numericos_cargados_como_null` (código 1).
- Columnas con espacios o tildes van entre comillas dobles: `SELECT "año" FROM t`.
- No se permite modificar, crear, adjuntar ni varias sentencias: responde error (código 2).

`--show N` (20; 0–100) muestra las primeras filas en la terminal: **son valores de celdas**, también
con `--json`. `--show 0` solo las oculta de la terminal: el resultado completo sigue guardado en
`validos.csv` y `validos.json`, que requieren el mismo cuidado.

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
- **Omisión de `--numeric`.** Sobre texto SQLite calcula mal sin avisar: `SUM` de `2,5` y `3,5` da 5,
  `'10,5' < '9,5'` y `v > 3` compara letras. Protección: si la consulta lee una columna de texto
  cuyos valores son en su mayoría números y alguno tiene decimales (sin códigos con ceros
  iniciales), el kit la repite en memoria con esa columna como número; si el resultado cambia,
  publica igualmente el resultado como texto, pero con la advertencia
  `resultado_depende_de_texto_sin_numeric` (código 1) y la sugerencia `--numeric columna`.
  No analiza el SQL. Alcance: no avisa por columnas solo de enteros (su `SUM` es correcto, pero
  orden, `MAX` y comparaciones siguen siendo de texto), ni con mayoría de valores no numéricos.
  Falsos positivos: tratar a propósito como texto una columna con decimales (`LENGTH(v)`,
  `v || ' h'`, `v = '2,50'`), funciones aleatorias, u orden distinto de filas sin `ORDER BY`.
  La repetición duplica tiempo y memoria solo en ese caso.

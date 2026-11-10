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
  `'10' < '9'` como texto. Para sumar, promediar u ordenar numéricamente declara las columnas
  con `--numeric col1 col2`; se interpretan con `--decimal`. Un valor no numérico queda `NULL`
  y se avisa con `valores_no_numericos_cargados_como_null` (código 1).
- Los números se cargan como decimales binarios: para sumas exactas al dígito usa `transformar`.
- Columnas con espacios o tildes van entre comillas dobles: `SELECT "año" FROM t`.
- No se permite modificar, crear, adjuntar ni varias sentencias: responde error (código 2).

`--show N` (20; 0–100) muestra las primeras filas en la terminal: **son valores de celdas**.
Con datos sensibles usa `--show 0`. El resultado completo queda en `validos.csv` y `validos.json`.

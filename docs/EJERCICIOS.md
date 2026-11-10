# Ejercicios con datos mineros ficticios

Datos en `examples/minera/` (octubre de 2026, inventados; `scripts/datos_mineros.py` los genera).
Separador `;` y coma decimal. Intenta cada ejercicio antes de mirar la respuesta.

| Archivo | Contenido |
|---|---|
| `flota.csv`, `flota_anterior.csv` | 44 equipos: camiones, palas, perforadoras, cargadores, chancadores, correas |
| `flota_excel_windows.csv` | La misma flota guardada como lo hace Excel en Windows |
| `ordenes.csv` | 600 órdenes de mantención, con errores puestos a propósito |
| `detenciones.csv` | 450 detenciones con causa, horas y turno |
| `produccion/turno_A.csv`, `turno_B.csv` | Viajes y toneladas por camión y día |
| `combustible.csv` | Litros diarios por camión |

## 1. Conocer un archivo
`./kit inspeccionar examples/minera/flota.csv`
¿Qué pasa? Sale un aviso y una sugerencia. Repite con `--delimiter ';'`.
**Respuesta:** 44 filas, columnas equipo, tipo, modelo, area, año, estado.

## 2. Archivo de Excel en Windows
`./kit inspeccionar examples/minera/flota_excel_windows.csv --delimiter ';'`
**Respuesta:** error de codificación; funciona agregando `--encoding cp1252`.

## 3. Buscar errores
`./kit validar examples/minera/ordenes.csv --delimiter ';' --rules examples/minera/reglas_ordenes.json`
Abre `reglas_ordenes.json` y `incidencias.csv` del resultado.
**Respuesta:** 568 válidas y 32 inválidas. 10 órdenes repetidas (5 pares), 6 vacíos (4 equipos,
2 horas), 6 fechas en formato día/mes/año, 4 estados mal escritos, 3 horas negativas, 3 sobre 72.

## 4. Validar otro archivo
`./kit validar examples/minera/combustible.csv --delimiter ';' --rules examples/minera/reglas_combustible.json`
**Respuesta:** 9 filas inválidas: 5 sin litros y 4 con litros negativos.

## 5. Qué cambió en la flota
`./kit comparar examples/minera/flota_anterior.csv examples/minera/flota.csv --delimiter ';' --key equipo`
**Respuesta:** 2 equipos nuevos, 1 eliminado (CAEX-099), 6 con el estado cambiado. Ver `cambios.csv`.

## 6. Juntar los turnos
`./kit consolidar examples/minera/produccion --delimiter ';'`
**Respuesta:** 2 archivos aceptados, 1 280 filas, con columnas de procedencia.

## 7. Horas por equipo, y por qué validar primero
`./kit transformar examples/minera/ordenes.csv --delimiter ';' --plan examples/minera/plan_horas_por_equipo.json`
**Respuesta:** el primero es CAEX-012 con 1 672,5 horas en 8 órdenes: imposible. Es una de las órdenes
con horas sobre 72. Repite usando `validos.csv` del ejercicio 3 como entrada y el resultado cambia.

## 8. SQL: contar por estado
```bash
./kit consultar examples/minera/ordenes.csv --delimiter ';' \
  --sql "SELECT estado, COUNT(*) AS n FROM t GROUP BY estado ORDER BY n DESC"
```
**Respuesta:** cerrada 423, abierta 109, en proceso 64, y cuatro variantes mal escritas con 1 cada una.

## 9. SQL: horas detenidas por causa
```bash
./kit consultar examples/minera/detenciones.csv --delimiter ';' --decimal ',' --numeric horas \
  --sql "SELECT causa, COUNT(*) AS detenciones, ROUND(SUM(horas),1) AS horas FROM t GROUP BY causa ORDER BY horas DESC"
```
**Respuesta:** falla mecánica 108 detenciones y 553,2 h; mantención programada 80 y 466,1 h; operacional 78 y 415,9 h.

## 10. SQL con JOIN: órdenes de equipos que no existen
```bash
./kit consultar examples/minera/ordenes.csv --delimiter ';' --tabla flota=examples/minera/flota.csv \
  --sql "SELECT t.orden, t.equipo FROM t LEFT JOIN flota f ON f.equipo = t.equipo WHERE f.equipo IS NULL AND t.equipo <> ''"
```
**Respuesta:** OT-000067 (CAEX-271), OT-000329 (CAEX-243), OT-000531 (CAEX-249). `validar` no lo detecta:
revisa cada archivo por separado; cruzar dos tablas requiere SQL.

## 11. SQL: disponibilidad por equipo
Disponibilidad = horas no detenido / horas del mes (31 × 24 = 744).
```bash
./kit consultar examples/minera/detenciones.csv --delimiter ';' --decimal ',' --numeric horas \
  --tabla flota=examples/minera/flota.csv --show 5 \
  --sql "SELECT t.equipo, f.modelo, ROUND(SUM(t.horas),1) AS horas_detenido, ROUND(100 - SUM(t.horas)*100.0/744, 1) AS disponibilidad FROM t JOIN flota f ON f.equipo = t.equipo GROUP BY t.equipo ORDER BY horas_detenido DESC"
```
**Respuesta:** la peor es PALA-001 con 136 h detenida (81,7 %); siguen CORR-004 (83,7 %) y CORR-003 (85,3 %).

## 12. Por tu cuenta
- ¿Qué camión consume más litros por día en promedio? (CAEX-017, 3 848 litros, ignorando vacíos y negativos.)
- ¿Cuántas toneladas movió el turno A en el mes? (2 711 834 en 9 431 viajes.)
- ¿Qué equipo tiene más órdenes correctivas? (CAEX-006, con 11.)
- Anota lo que hiciste hoy: `./kit bitacora "Ejercicios 1 a 12 del kit" --horas 2 --etiqueta estudio`.

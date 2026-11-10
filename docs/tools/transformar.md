# Transformar

```bash
python -B kit.py transformar 'examples/entradas/turno A.csv' --delimiter ';' --plan examples/plan.json
```

Solo se acepta un objeto `{"steps": [...]}`; los pasos se ejecutan en orden y el informe
registra filas antes/después. No hay código ejecutable, expresiones ni SQL. Las filas
originales permanecen intactas. Un paso inválido o una conversión imposible falla toda
la transformación con código 2. No se publican resultados transformados parciales.

| op | Parámetros |
|---|---|
| select | `columns`: lista no vacía; también fija orden de salida |
| filter | `column`, `operator`, `value`; `type` opcional (string por defecto) |
| sort | `columns`; `descending` booleano, `type` opcional común a las claves |
| convert | `column`, `type`; conversión explícita |
| deduplicate | `keys`: conserva la primera fila por clave, solo si se solicita |
| group | `by`: columnas o [] para total general; `aggregates`: lista |

Tipos: string, integer, number, date, boolean. `decimal` y `date_format` pueden
sobrescribirse en filter/sort/convert; group admite decimal.
Filtros: eq, ne, gt, ge, lt, le, contains (solo texto). Vacíos se interpretan como null
al filtrar/ordenar; `eq null` identifica vacíos y `ne null` los excluye. Orden ascendente
coloca vacíos al final y descendente al principio. Orden estable; texto distingue
mayúsculas. Sin type numérico, `10` precede lexicográficamente a `2`.

Ejemplo de conversión, orden numérico y deduplicación explícita:

```json
{"steps": [
  {"op": "convert", "column": "horas", "type": "number", "decimal": ","},
  {"op": "sort", "columns": ["horas"], "type": "number", "decimal": "."},
  {"op": "deduplicate", "keys": ["orden"]}
]}
```

Cada agregado admite `op`, `as` y `column`. Operaciones: count (sin columna cuenta
filas; con columna cuenta no vacíos), sum, mean, min, max (numéricas, ignoran vacíos).
Sin valores numéricos el resultado es null; sin filas no se crea ningún grupo.
Alias no pueden repetirse ni coincidir con las claves. Ejemplo:

```json
{"steps": [{"op": "group", "by": ["equipo"], "decimal": ",", "aggregates": [
  {"op": "count", "as": "ordenes"},
  {"op": "sum", "column": "horas", "as": "total_horas"}
]}]}
```

Números resultantes son textos decimales con punto. Sum amplía precisión; mean puede
redondear a 28 dígitos. Las fechas convertidas son YYYY-MM-DD. No aplicar conversión
integer a identificadores si debes conservar ceros: ese paso los quitaría explícitamente.

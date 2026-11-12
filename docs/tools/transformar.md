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
| deduplicate | `keys`: conserva la primera fila por clave, solo si se solicita; no distingue idénticas de contradictorias (ver paso `duplicados` de recetas) |
| group | `by`: columnas o [] para total general; `aggregates`: lista |
| rename | `columns`: `{"actual": "nuevo"}`; ver abajo |
| normalize | `columns`: lista; `case` opcional upper/lower; ver abajo |
| replace | `column`, `map` y `unknown` (obligatorio); ver abajo |

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

## Renombrar (`rename`)

`{"op": "rename", "columns": {"Orden": "orden", "Equipo": "equipo"}}`: solo cambia nombres de
columnas, nunca valores; el resto conserva nombre y orden. Se rechaza (código 2) si dos columnas
recibirían el mismo nombre, si el nombre nuevo choca con una columna que no se renombra o si
una columna de origen no existe (mayúsculas, tildes y espacios cuentan). Un intercambio
explícito (`{"a": "b", "b": "a"}`) es válido. En recetas la procedencia de cada fila no cambia y
`report.json` registra el mapeo aplicado.

Desde 1.5.0-etapa3, **toda** configuración JSON (planes, reglas, recetas) con una clave repetida
en un mismo objeto es un error (`Clave JSON repetida`), en vez de quedarse en silencio con la
última. Es un cambio de compatibilidad deliberado: una regla o mapeo duplicado casi siempre
es una errata que antes pasaba inadvertida.

## Normalizar texto (`normalize`)

`{"op": "normalize", "columns": ["orden", "estado"], "case": "lower"}`: solo en las columnas
indicadas, quita espacios en blanco de los extremos y deja cada racha interior en un espacio
(cuenta como espacio también el tabulador y el no separable). `case` (`upper`/`lower`) es
opcional; sin él no se tocan mayúsculas. No quita tildes, no convierte tipos y no toca ceros
iniciales (`" 0042 "` → `"0042"`). En recetas cada celda cambiada va a `cambios_celdas.csv`.
Si dos valores distintos pasan a ser iguales (`" OT1 "` y `"OT1"`), `report.json` lo cuenta en
`valores_unificados`; para detectar las claves que chocan usa después `validar` con `unique`
o el paso `duplicados` de las recetas.

## Reemplazar por equivalencias (`replace`)

`{"op": "replace", "column": "estado", "map": {"Abierta": "abierta", "Cerrada": "cerrada"}, "unknown": "keep"}`.
Coincidencia **exacta** (mayúsculas, tildes y espacios cuentan; `"abierta "` no es `"abierta"`:
normaliza antes si hace falta). Un valor que ya es un destino del mapa (`abierta`) es válido y no
cambia. Las celdas vacías no se tocan salvo que el mapa tenga la clave `""`. `unknown` decide qué
pasa con un valor que no está en el mapa:

| unknown | Efecto |
|---|---|
| `keep` | Se conserva y se avisa `valor_sin_equivalencia` (código 1). En recetas detiene salvo `advertencias_permitidas` |
| `exclude` | La fila sale del resultado; en recetas va a `excluidas.csv` con el motivo |
| `error` | La transformación falla entera (código 2), sin resultado |

No hay coincidencias aproximadas ni equivalencias deducidas. En recetas cada reemplazo va a
`cambios_celdas.csv`. Con `transformar` suelto las filas excluidas no se guardan aparte (igual que
`filter`); usa una receta si necesitas conservarlas.

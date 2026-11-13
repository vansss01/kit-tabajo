# Ejecutar (recetas)

```bash
./kit ejecutar 'examples/con incidencias.csv' --receta recetas/revision_ordenes.json --vista-previa
./kit ejecutar 'examples/con incidencias.csv' --receta recetas/revision_ordenes.json --json
./kit ejecutar otro.csv --receta mi_receta.json --entrada anterior=mes_pasado.csv
```

Una receta es un JSON (sin código) con pasos que usan los comandos existentes, en orden.
El archivo de la línea de comandos es la entrada `principal`; `--entrada NOMBRE=ARCHIVO`
reemplaza otra. La misma receta sirve para otro archivo compatible cambiando solo la ruta.

## Recetas de ejemplo

Tres recetas completas en `recetas/`, con entradas ficticias en `examples/recetas/` y el resultado
esperado **escrito a mano** en `examples/recetas/esperados/<receta>.json` (estado, filas por paso,
incidencias por código, filas clave). `tests/test_recetas_ejemplo.py` las ejecuta por la CLI y compara
contra ese esperado, y repite cada una sobre un segundo archivo cambiando solo la ruta.

| Receta | Pasos | Entrada principal → resultado esperado | Segundo archivo |
|---|---|---|---|
| `revision_ordenes.json`: inspeccionar, validar (separar), resumir y entregar | perfil, revision, resumen, entrega (CSV + XLSX) | `ordenes_semana_1.csv` (10 órdenes): 3 aceptadas, 7 rechazadas, 7 incidencias (orden repetida ×2, fecha `03/11/2026` ambigua, equipo vacío, horas 25 y −1,0, horas vacía); resumen `0007 → 2 órdenes, 3.0 h` | `ordenes_semana_2.csv`: 5 aceptadas, 0 rechazadas, `completada` |
| `consolidacion_turnos.json`: adaptar nombres de columnas, consolidar, apartar repetidas y resumir solo las conservadas | adaptar (`rename`), union (`consolidar`), repetidas (`duplicados`, separar), resumen, entrega | `turno_a.csv` + `turno_b_exportado.csv` (columnas `OT/Equipo/Fecha/Hrs/Estado`): 8 filas unidas; OT302 idéntica → `excluidas`; OT303 con horas 1,0 y 3,0 → `conflictos` (2 incidencias); 5 conservadas; resumen por equipo 2.5 / 3.5 / 4.5 | `turno_a_semana_2.csv` con `--entrada turno_b=…semana_2_exportado.csv`: 3 conservadas, 1 idéntica excluida, `completada` |
| `enriquecimiento_flota.json`: completar modelo y área desde la flota, apartar claves inexistentes, ambiguas o vacías, resumir por área | enriquecer (`completar`, separar), resumen, entrega | `ordenes_flota.csv` + `flota.csv` (0042 repetido): 3 completadas, 1 `sin_coincidencia` (0099), 1 `ambiguas` (0042), 1 `clave_vacia`; 5 incidencias (2 por la clave repetida en la referencia); resumen Agua 3.0 / Taller 1.5 | `ordenes_flota_semana_2.csv`: 2 completadas; la referencia sigue aportando sus 2 incidencias |

```bash
./kit ejecutar examples/recetas/ordenes_semana_1.csv --receta recetas/revision_ordenes.json
./kit ejecutar examples/recetas/turno_a.csv --receta recetas/consolidacion_turnos.json \
    --entrada turno_b=examples/recetas/turno_b_exportado.csv
./kit ejecutar examples/recetas/ordenes_flota.csv --receta recetas/enriquecimiento_flota.json
```

Para usarlas con tus archivos: copia la receta, cambia `ruta` de las entradas secundarias (o pásalas
con `--entrada`) y ajusta reglas, mapeo de `rename`, clave y columnas. Lo que no se decide por ti sigue
igual: sin `conservar` los conflictos van a `conflictos`; sin `existentes` no se pisa ningún dato.

```json
{"version": 1, "nombre": "revision_ordenes",
 "entradas": {"ordenes": {"principal": true, "delimiter": ";", "decimal": ","},
              "anterior": {"ruta": "../examples/anterior.csv", "delimiter": ";"}},
 "salida": {"delimiter": ";"},
 "pasos": [
  {"nombre": "perfil", "op": "inspeccionar", "entrada": "ordenes"},
  {"nombre": "revision", "op": "validar", "entrada": "ordenes", "reglas": "../examples/reglas.json",
   "politica": {"incidencias": "separar"}},
  {"nombre": "resumen", "op": "transformar", "entrada": "revision.aceptadas", "plan": "../examples/plan.json"},
  {"nombre": "cambios", "op": "comparar", "antes": "anterior", "despues": "revision.aceptadas", "clave": ["orden"]},
  {"nombre": "entrega", "op": "exportar", "archivo": "entrega", "formatos": ["csv", "xlsx"],
   "tablas": {"aceptadas": "revision.aceptadas", "rechazadas": "revision.rechazadas"}}]}
```

- `version` es obligatoria (hoy `1`). Campos desconocidos son error, para no ignorar erratas.
- **Entradas**: `ruta` (relativa a la receta), `principal`, `delimiter` (`"TAB"` admitido),
  `encoding`, `decimal`, `date_format`, `sheet`, `politica`, `fila_encabezado`, `excluir_filas`.
  Una entrada sin uso es error.
- **Referencias**: el nombre de una entrada o `paso.salida` de un paso **anterior**; nunca rutas.
  Salidas: validar → `aceptadas`, `rechazadas`, `incidencias`; transformar y consultar →
  `resultado`; consolidar → `resultado`, `incidencias`; comparar → `nuevos`, `eliminados`,
  `cambios`; completar → `completadas`, `sin_coincidencia`, `ambiguas`, `clave_vacia`,
  `incidencias`; duplicados → `conservadas`, `excluidas`, `conflictos`, `incidencias`. inspeccionar
  y exportar solo dejan informe/archivos.
- **Parámetros**: inspeccionar `entrada`, `sample` (0 por defecto: sin muestras de celdas);
  validar `entrada`, `reglas`; transformar `entrada`, `plan` (objeto o ruta, mismo formato que
  `--rules`/`--plan`); consultar `tablas` `{alias: ref}`, `sql`, `numeric`; consolidar
  `entradas` (lista); comparar `antes`, `despues`, `clave`; exportar `tablas` `{hoja: ref}`,
  `formatos` (csv/json/xlsx), `archivo`, `safe_csv`. Todos admiten `opciones`
  (`decimal`, `date_format`); si no, heredan las de la entrada de origen.
- La única ramificación es usar las salidas separadas (`revision.aceptadas` o
  `revision.rechazadas`, etc.). No hay bucles, condiciones ni pasos en paralelo.
- Operaciones de plan útiles en recetas (`rename`, `normalize`, `replace`): manual de
  [transformar](transformar.md).

## Exportes con títulos y pies (`fila_encabezado`, `excluir_filas`)

Para CSV o XLSX con títulos arriba y totales abajo (no JSON):

```json
"ordenes": {"principal": true, "delimiter": ";", "fila_encabezado": 3,
            "excluir_filas": [{"columna": "orden", "igual": "TOTAL"},
                              {"columna": "orden", "empieza_con": "Fin"}],
            "politica": {"incidencias": "separar"}}
```

- `fila_encabezado`: número de fila del encabezado; las anteriores se omiten. Las filas de
  datos conservan su **número real** (la primera es `fila_encabezado + 1`) en procedencia e
  incidencias.
- `excluir_filas`: cada condición nombra una `columna` del encabezado y **una** prueba:
  `igual` (texto exacto), `empieza_con` o `"vacia": true`. Se mira por posición, así que
  también sirve para un pie de un solo campo. Las filas excluidas van a
  `00-entradas/excluidas.csv` con la fila real, el motivo y sus valores.
- No se adivina: una fila de total que no cumple ninguna condición sigue siendo un dato (y
  validar puede rechazarla); una fila de otro ancho sigue siendo `ancho_incorrecto`.
- Invariante de lectura: filas leídas = tabulares + mal formadas + excluidas por condición.

## Completar desde una referencia (`completar`)

```json
{"nombre": "flota", "op": "completar", "entrada": "ordenes", "referencia": "equipos",
 "clave": ["equipo"], "columnas": ["area", "modelo"], "existentes": "completar_vacios",
 "politica": {"incidencias": "separar"}}
```

Busca cada fila en la referencia por la clave, **texto exacto** (`"7"` no es `"0007"`); la
clave puede ser compuesta y llamarse distinto en la referencia (`clave_referencia`, mismo
largo). Copia solo las `columnas` pedidas, como texto (comas decimales, fechas y ceros tal cual).
Cada fila de entrada termina en **una** salida, nunca se duplica:

| Salida | Cuándo | Incidencia |
|---|---|---|
| `completadas` | Exactamente una fila de la referencia con esa clave | — |
| `sin_coincidencia` | Ninguna | `clave_sin_coincidencia` |
| `ambiguas` | Dos o más (no se elige ninguna) | `coincidencia_ambigua` |
| `clave_vacia` | Alguna columna de la clave vacía | `clave_vacia` |

La referencia también se revisa: filas sin clave (`clave_vacia_en_referencia`) y claves
repetidas (`clave_duplicada_en_referencia`, aunque las filas sean idénticas; deduplícala antes).
Invariante: entrada = completadas + sin_coincidencia + ambiguas + clave_vacia.

`existentes` decide qué pasa si una columna pedida ya existe en la entrada: `error` (por
defecto, no se ejecuta), `completar_vacios` (solo celdas vacías; un dato presente distinto se
conserva y se cuenta en `celdas_presentes_distintas`) o `reemplazar` (todo, registrado). Cada
celda escrita sobre una columna existente va a `cambios_celdas.csv`. Sin `politica`, cualquier
fila sin completar o problema de la referencia detiene; con `separar` se sigue con `completadas`.

## Duplicados (`duplicados`)

```json
{"nombre": "dup", "op": "duplicados", "entrada": "ordenes", "clave": ["orden"],
 "conservar": "mas_reciente", "fecha": "fecha", "empate": "conflicto",
 "politica": {"incidencias": "separar"}}
```

Agrupa por `clave` y separa cada fila en una salida (invariante: entrada = conservadas +
excluidas + conflictos; `*_procedencia.csv` trae el motivo de cada una):

- **Idénticas** (mismos valores en las columnas comparadas): se conserva la primera y las
  demás van a `excluidas` («idéntica a … fila N»). Se comparan todas las columnas salvo las de
  procedencia de consolidar (`__…`); `comparar` elige otras.
- **Contradictorias** (misma clave, valores distintos): van a `conflictos` con las columnas que
  difieren, salvo `conservar` explícito: `primero`, `ultimo` u `mas_reciente`. Las perdedoras
  van a `excluidas` con el motivo y la fila conservada.
- `mas_reciente` exige `fecha` (formato: `date_format` de la entrada u `opciones`). Si alguna
  fecha del grupo es vacía o inválida, todo el grupo va a `conflictos`. Un **empate** en la
  fecha más reciente es conflicto por defecto; `empate`: `primero` o `ultimo` lo resuelve.
- Clave vacía: `conflictos`. Cada conflicto es una incidencia (`conflicto_de_duplicados`,
  `clave_vacia`): sin `politica` detiene; con `separar` se sigue con `conservadas`.

La operación `deduplicate` de los planes no cambia: conserva la primera fila de cada clave sin
distinguir idénticas de contradictorias (en recetas, las demás van a `excluidas.csv`). Para
decidir con criterio usa este paso.

## Políticas

`"politica": {"incidencias": "detener" | "separar", "advertencias_permitidas": ["codigo"]}`,
en cada paso o entrada. Sin política: **detener** ante cualquier incidencia o advertencia.

- `separar` solo existe para validar (las filas inválidas van a `rechazadas`), completar (a
  `sin_coincidencia`, `ambiguas`, `clave_vacia`), duplicados (a `conflictos`), consolidar (los archivos incompatibles quedan
  fuera) y entradas (filas mal formadas fuera, registradas en `00-entradas/incidencias.csv`).
  Las demás operaciones solo pueden detenerse.
- Permitir una advertencia no autoriza otras: se enumeran códigos exactos, sin comodines.
- Separar o permitir **no oculta** nada: el paso queda `completado_con_incidencias` y la
  ejecución termina con código 1.
- Un error de ejecución (columna inexistente, conversión imposible…) siempre detiene.
- Un paso detenido deja su `report.json` e `incidencias.csv`, pero no sus tablas.

## Vista previa y comprobación

La receta se comprueba **completa** antes de leer datos: estructura, operaciones, parámetros,
referencias, reglas y planes. Si falla, código 2, nada se crea y cada error trae `codigo`
estable, `paso`, `campo`, `mensaje` y `sugerencia`.

Después se leen **solo los encabezados** (CSV/XLSX; ninguna fila) y cada paso se ejecuta sobre
tablas vacías con las mismas funciones de la ejecución real: así se detectan columnas
inexistentes en planes, claves de comparar, `numeric` y el propio SQL. Un error aquí
(`columnas_incompatibles`, o `encabezado_ilegible` si el encabezado no se puede leer) detiene
`ejecutar` antes de crear la carpeta. Las tablas JSON no se
pueden leer solo por el encabezado: se marcan `no_comprobado` y sus pasos `no_comprobadas`.

`--vista-previa` muestra entradas, pasos, políticas, destinos y el estado de columnas de cada
paso, y termina sin escribir nada. Código 0 sin problemas, 1 con avisos (p. ej.
`incidencias_previstas` por una columna obligatoria ausente), 2 si la ejecución fallaría.
**No valida datos**: las filas no se leen.

## Resultados y manifiesto

Carpeta nueva por ejecución: `00-entradas/`, una carpeta `NN-paso/` por paso con sus tablas
(CSV y JSON), `report.json` y, si corresponde, `incidencias.*`; además `report.json`,
`audit.json` y `manifiesto.json`. Solo `manifiesto.json` se reescribe, siempre de forma
atómica (temporal + renombrado), tras cada paso; el estado final es lo último que se escribe.

| Estado (ejecución) | Significado | Código |
|---|---|---|
| `en_curso` | En marcha, o cortada de golpe: **no usar** | — |
| `completada` | Todos los pasos sin incidencias ni advertencias | 0 |
| `completada_con_incidencias` | Todos los pasos; hubo separaciones o advertencias permitidas | 1 |
| `fallida` | `motivo`: `detenida_por_politica`, `error_de_ejecucion` o `interrumpida`; hay `FAILED.json` | 2 |

| Estado (paso) | Significado |
|---|---|
| `pendiente` | No llegó a ejecutarse (un paso anterior se detuvo o falló) |
| `en_curso` | Ejecutándose; si la ejecución ya no corre, se cortó: sus archivos no valen |
| `completado` / `completado_con_incidencias` | Terminó; el segundo con filas apartadas o advertencias permitidas |
| `detenido` | Su política no admitía lo encontrado: deja `report.json` e `incidencias.csv`, no tablas |
| `fallido` | Error o invariante incumplida: no deja tablas |
| `interrumpido` | Ctrl+C durante el paso |

Cada tabla del manifiesto lleva `validada`: es `true` solo para `aceptadas` de un paso validar;
lo filtrado, transformado o consultado nunca es "validado".

## Trazabilidad

Cada fila recuerda su **entrada, archivo y fila original** (fila 1 = encabezado) como dato
interno: no se añade ninguna columna a las tablas. Se escribe en archivos auxiliares del paso:

| Archivo | Contenido |
|---|---|
| `<salida>_procedencia.csv` | `fila` de la tabla del paso → `entrada`, `archivo`, `fila_origen`; en `rechazadas`, también `motivos` |
| `excluidas.csv` (transformar) | Filas que quitó un `filter` o `deduplicate`, con `paso_plan`, `motivo`, origen y la fila tal como estaba |
| `cambios_celdas.csv` (transformar) | Registro, `columna`, `valor_anterior`, `valor_nuevo`, `operacion` (hoy solo `convert`) |
| `participantes.csv` (transformar con `"traza": "detallada"`) | Qué fila original entra en cada grupo de `group` |
| `cambios_procedencia.csv` (comparar) | Para cada línea de `cambios`, la fila original de antes y de después |
| `00-entradas/incidencias.csv` | Filas mal formadas que no entraron al flujo (`ancho_incorrecto`) |

Dónde quedan las filas que no siguen: rechazadas por validar → `NN-paso/rechazadas.*`;
excluidas por filtro o deduplicación → `excluidas.csv`; archivos rechazados por consolidar →
`incidencias.csv` y `report.json` (`rechazados`); mal formadas → `00-entradas/incidencias.csv`.
Las incidencias y `__fila_origen` de consolidar citan siempre el archivo y la fila originales.

Sin procedencia por fila: los resultados de `group` (el manifiesto da la regla para reconstruir
qué filas participaron; `participantes.csv` si se pide) y de `consultar` (participan como
candidatas todas las filas de las tablas leídas, listadas en `participacion`).

En el manifiesto, cada paso trae `filas` (`entrada`, `salidas`, `rechazadas`, `excluidas`,
`cambios_celdas`), `trazas` (rutas), `detalles` (`report.json`) e `invariantes`, comprobadas
**antes** de publicar las tablas; si una falla, el paso queda `fallido` sin tablas:

- partición (validar, consolidar, transformar sin `group`): entrada = salidas + apartadas,
  con las mismas filas de origen;
- participación (transformar con `group`): cada fila de origen termina en el resultado, en
  excluidas o en un grupo; no se compara la cantidad de filas;
- claves (comparar): antes = eliminadas + comunes y después = nuevas + comunes;
- ninguna (consultar, inspeccionar): SQL puede combinar o repetir filas.

**Validar, transformar o completar.** `validar` solo señala y separa (`aceptadas` es lo único
`validada: true`); `transformar` calcula una tabla nueva (filtrar, convertir, agrupar, renombrar,
normalizar, reemplazar) y registra cada fila quitada y cada celda cambiada; `completar` corrige desde
una fuente: copia columnas de una referencia por clave exacta, sin elegir entre coincidencias ni pisar
datos presentes salvo `existentes`. Ninguna toca el archivo original.

**Revisar un cambio:** abre `manifiesto.json`, busca el paso, y en sus `trazas` el archivo.
Ejemplo: ¿por qué falta la orden OT2? → `03-limpieza/excluidas.csv` dice
`no cumple estado eq abierta`, `turno A.csv`, fila 3. Estos archivos contienen valores de
celdas: trátalos como los datos originales.

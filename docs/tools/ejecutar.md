# Ejecutar (recetas)

```bash
./kit ejecutar 'examples/con incidencias.csv' --receta recetas/revision_ordenes.json --vista-previa
./kit ejecutar 'examples/con incidencias.csv' --receta recetas/revision_ordenes.json --json
./kit ejecutar otro.csv --receta mi_receta.json --entrada anterior=mes_pasado.csv
```

Una receta es un JSON (sin código) con pasos que usan los comandos existentes, en orden.
El archivo de la línea de comandos es la entrada `principal`; `--entrada NOMBRE=ARCHIVO`
reemplaza otra. La misma receta sirve para otro archivo compatible cambiando solo la ruta.

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
  `encoding`, `decimal`, `date_format`, `sheet`, `politica`. Una entrada sin uso es error.
- **Referencias**: el nombre de una entrada o `paso.salida` de un paso **anterior**; nunca rutas.
  Salidas: validar → `aceptadas`, `rechazadas`, `incidencias`; transformar y consultar →
  `resultado`; consolidar → `resultado`, `incidencias`; comparar → `nuevos`, `eliminados`,
  `cambios`. inspeccionar y exportar solo dejan informe/archivos.
- **Parámetros**: inspeccionar `entrada`, `sample` (0 por defecto: sin muestras de celdas);
  validar `entrada`, `reglas`; transformar `entrada`, `plan` (objeto o ruta, mismo formato que
  `--rules`/`--plan`); consultar `tablas` `{alias: ref}`, `sql`, `numeric`; consolidar
  `entradas` (lista); comparar `antes`, `despues`, `clave`; exportar `tablas` `{hoja: ref}`,
  `formatos` (csv/json/xlsx), `archivo`, `safe_csv`. Todos admiten `opciones`
  (`decimal`, `date_format`); si no, heredan las de la entrada de origen.
- La única ramificación es usar `revision.aceptadas` o `revision.rechazadas`. No hay bucles,
  condiciones ni pasos en paralelo.

## Políticas

`"politica": {"incidencias": "detener" | "separar", "advertencias_permitidas": ["codigo"]}`,
en cada paso o entrada. Sin política: **detener** ante cualquier incidencia o advertencia.

- `separar` solo existe para validar (las filas inválidas van a `rechazadas`), consolidar
  (los archivos incompatibles quedan fuera) y entradas (filas mal formadas fuera, registradas
  en `00-entradas/incidencias.csv`). Las demás operaciones solo pueden detenerse.
- Permitir una advertencia no autoriza otras: se enumeran códigos exactos, sin comodines.
- Separar o permitir **no oculta** nada: el paso queda `completado_con_incidencias` y la
  ejecución termina con código 1.
- Un error de ejecución (columna inexistente, conversión imposible…) siempre detiene.
- Un paso detenido deja su `report.json` e `incidencias.csv`, pero no sus tablas.

## Vista previa y comprobación

La receta se comprueba **completa** antes de leer datos: estructura, operaciones, parámetros,
referencias, reglas y planes. Si falla, código 2, nada se crea y cada error trae `codigo`
estable, `paso`, `campo`, `mensaje` y `sugerencia`. Las columnas se comprueban al ejecutar.

`--vista-previa` muestra entradas, pasos, políticas y destinos, y termina sin escribir nada.
**No valida datos**: solo comprueba la receta y que los archivos existen.

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

Pasos: `pendiente`, `en_curso`, `completado`, `completado_con_incidencias`, `detenido`,
`fallido`, `interrumpido`. Cada tabla del manifiesto lleva `validada`: es `true` solo para
`aceptadas` de un paso validar; lo filtrado, transformado o consultado nunca es "validado".
`__fila_origen` de consolidar se refiere a la tabla consolidada (la entrada o la salida del
paso usado), no siempre al archivo original.

# Comprobar y catálogo (para agentes)

```bash
./kit catalogo                                   # capacidades del kit en JSON
./kit comprobar recetas/revision_ordenes.json    # receta, plan o reglas: sin ejecutar nada
./kit comprobar mi_plan.json --tipo plan --json
./kit comprobar mi_receta.json --principal datos.csv
```

**`catalogo`** imprime un JSON generado desde el código (no es una lista escrita aparte): versión
del kit, de las recetas y de los esquemas (`schemas/`), comandos y sus argumentos, operaciones de
receta (parámetros, obligatorios, salidas, si pueden separar), operaciones de plan, valores
admitidos, políticas, códigos de salida, estados de ejecución y de paso, reglas semánticas y todos
los códigos de error, incidencia y advertencia con su significado (también en `docs/CODIGOS.md`).

**`comprobar ARCHIVO`** revisa **solo la configuración**: estructura, parámetros, referencias entre
pasos, reglas y planes (los mismos controles que `ejecutar` antes de leer datos). El tipo se deduce
(`pasos` → receta, `steps` → plan, `columns` → reglas) o se fuerza con `--tipo`. En una receta, la
entrada principal puede omitirse; con `--principal` se comprueba además que exista.

| Herramienta | Lee | Detecta | Escribe |
|---|---|---|---|
| `comprobar` | solo el JSON | errores de configuración | nada |
| `ejecutar --vista-previa` | JSON y encabezados | además columnas inexistentes | nada |
| `validar` / `ejecutar` | datos | incidencias en las filas | carpeta de resultados |

Código 0 si es válida, 2 si no. Cada error trae `codigo`, `paso`, `campo`, `mensaje` y
`sugerencia`; `--json` da el resultado estructurado (texto por defecto). La salida dice siempre su
alcance: «Solo configuración… No se leyeron datos ni encabezados». Nunca muestra valores de celdas.

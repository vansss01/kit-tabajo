# Esquemas de reglas, planes y recetas

Esquemas JSON (draft 2020-12), versión `x-version-esquema: 1`, en `schemas/`:
`reglas.schema.json` (`validar --rules`), `plan.schema.json` (`transformar --plan`) y
`receta.schema.json` (`ejecutar --receta`; incluye reglas y planes escritos dentro de la receta).

**Una sola fuente de verdad.** Los esquemas se generan desde las mismas tablas que usa la
validación (`operations.py`, `receta_modelo.py`) con `src/kitlib/esquemas.py`; no se editan a mano
(`python -B scripts/esquemas.py` los regenera). `tests/test_esquemas.py` comprueba que los publicados
coinciden con los generados y, sobre un corpus (ejemplos, recetas y casos de error de las pruebas),
que el esquema y el validador aceptan y rechazan lo mismo, leyendo el esquema con un intérprete
independiente. Se eligió generar en vez de validar leyendo el esquema porque la validación ya
existía con mensajes y códigos estables que agentes y pruebas usan.

**Qué no puede expresar un esquema** (lo acepta el esquema y lo rechaza el kit; código en
`esquemas.REGLAS_SEMANTICAS`):

| Regla | Qué exige | Dónde se comprueba |
|---|---|---|
| `clave_json_repetida` | Ninguna clave repetida en un mismo objeto JSON (también en `validar --rules`) | al leer el JSON (`tableio.unique_keys`) |
| `referencias` | Cada referencia nombra una entrada o una salida de un paso anterior | `receta_validacion.cargar_receta` |
| `nombres_unicos` | Pasos y entradas con nombres distintos | `cargar_receta` |
| `entradas` | Una sola principal, todas usadas, archivos existentes; títulos/pies solo CSV/XLSX | `cargar_receta` |
| `archivos_de_configuracion` | Reglas o plan dados como ruta existen y son válidos | `cargar_receta` |
| `parametros_relacionados` | `clave`/`clave_referencia` del mismo largo; `fecha` y `empate` solo con `mas_reciente` | `cargar_receta` |
| `plan_relacionados` | `contains` con texto; `sum`/`mean`/`min`/`max` con `column`; alias únicos; `rename` sin destinos repetidos | `operations.check_step` |
| `reglas_rangos` | `min`/`max` con tipo numérico o fecha, convertibles y `min` ≤ `max` | `operations.validate_config` |
| `columnas` | Las columnas usadas existen en los encabezados | `receta_vista.comprobar_columnas` (vista previa y antes de ejecutar) |

Otra diferencia: un número entero escrito con decimales (`"sample": 1.0`) es entero para JSON
Schema, pero el kit lo rechaza; escribe enteros sin decimales.

Comprobar una configuración sin ejecutar nada: `./kit comprobar ARCHIVO.json` (ver
`tools/comprobar.md`). Catálogo de capacidades: `./kit catalogo`.

# Estado del proyecto

Actualizado: 2026-11-13. Versión 1.5.0 (cierre de la etapa 5), publicada en `main` (commit f605d12).
Repositorio: `github.com/vansss01/kit-tabajo` (privado).
Comprobado en local (Linux, Python 3.14.9): 122 pruebas, Ruff y mypy con `scripts/check.py`, flujo
`scripts/demo.py` y 97/97 mutaciones (`scripts/mutaciones.py`). La CI (`.github/workflows/check.yml`:
`check.py`, `demo.py`, instalación sin red y lanzadores) pasó en **Linux y Windows con Python 3.11 y
3.14** sobre ese commit (run 43480431875, 2026-11-13). Sin dependencia de proveedores de IA.

Comandos: inspeccionar, comparar, consolidar, validar, transformar, exportar, consultar,
ejecutar, bitacora, limpiar, catalogo, comprobar, resultados. Recetas de ejemplo: `recetas/`
(revisión de órdenes, consolidación de turnos, enriquecimiento con flota).

## Cambios de 1.5.0-etapa5 (auditoría, recetas de ejemplo, mediciones y cierre)

- Auditoría de la etapa 4 contra lo pedido: todo estaba implementado y probado; lo único que faltaba
  era documentar en `tools/validar.md` que una clave JSON repetida también es error con `--rules`
  suelto (ya lo era en el código y en una prueba). La CI no necesitó cambios.
- Tres recetas completas con entradas ficticias (`examples/recetas/`) y **resultados esperados escritos
  a mano** (`examples/recetas/esperados/`): `revision_ordenes` (3 aceptadas, 7 rechazadas, 7
  incidencias), `consolidacion_turnos` (`rename` + `consolidar` + `duplicados`: 5 conservadas, 1 idéntica,
  2 en conflicto) y `enriquecimiento_flota` (`completar`: 3 completadas, 1 sin coincidencia, 1 ambigua,
  1 clave vacía). Cada una se repite sobre un segundo archivo cambiando solo la ruta
  (`tests/test_recetas_ejemplo.py`, dirigido por los esperados).
- Pruebas pendientes (`tests/test_compatibilidad.py`): un comando suelto y el mismo paso de receta
  producen las mismas filas e incidencias (validar, transformar, consolidar); el resumen `--json` de
  `ejecutar` no arrastra detalles y `resultados` respeta sus topes (30 pasos, 40 archivos, 15 códigos,
  100 incidencias, 200 caracteres) sobre una ejecución fabricada mayor; con `--ocultar-valores` ninguna
  celda de las recetas de ejemplo llega a la terminal ni a los JSON. 11 mutaciones nuevas (el
  mensaje del commit 5748805 dice 12: una resultó redundante y se retiró antes de commitear).
- `scripts/medir.py`: conjunto generado con semilla (no se commitea), tiempos, memoria y tamaños;
  resultados y condiciones en `MEDICIONES.md`. No se añade procesamiento distribuido: 100 000 filas
  usan como máximo 181 MiB.
- Documentación: `AGENT_GUIDE.md` con tabla «Dónde está cada respuesta» y la distinción validar /
  transformar / completar; `tools/ejecutar.md` con las recetas de ejemplo; `APRENDER.md` con la etapa 5 y
  el índice «¿qué comando uso para…?»; `docs/REPORTE_KIT.html` (página autocontenida, 1.5.0).
- Versión `1.5.0` en `kitlib.__version__` (antes `1.5.0-etapa4`); sin cambios de comportamiento.

## Cambios de 1.5.0-etapa4 (contrato para agentes y SQL)

- `recetas.py` dividido en `receta_modelo`, `receta_validacion`, `receta_vista`, `receta_cli` y
  `recetas` (ejecución), sin cambiar comportamiento.
- `schemas/*.schema.json` generados desde las tablas de la validación (`esquemas.py`), con prueba de
  equivalencia contra un intérprete independiente y reglas semánticas listadas (`ESQUEMAS.md`).
- `catalogo` (JSON desde el código), `comprobar` (solo configuración), `resultados` (resumen, paso,
  N incidencias con tope 100), registro único de códigos (`codigos.py`, `CODIGOS.md`).
- Errores estructurados: con `--json` todo error trae `errores` con código, campo y sugerencia.
- `--ocultar-valores` en comandos de tablas y `ejecutar`; tabla de salidas con valores en `DATA_POLICY`.
- `consultar`: `--tipo TABLA.COLUMNA=number|string` (recetas: `tipos`); detector de texto numérico
  configurable y con límite de filas (`detector_texto_numerico_omitido` al superarlo).
- **Compatibilidad**: el validador de planes ahora rechaza al comprobar `convert` con `column` no
  textual, `date_format` no textual, `value` de `filter` lista u objeto y `column` de agregado no
  textual (antes fallaban o hacían algo sin sentido al ejecutar). Lo demás es aditivo (`errores` en
  `--json`, opciones y comandos nuevos); la salida por defecto no cambia. Código Python que importaba
  `cargar_receta`, `vista_previa`, `add_parser` o `run` desde `kitlib.recetas` debe usar los módulos
  nuevos.

## Cambios de 1.5.0-etapa3 (transformaciones controladas)

- Plan: `rename` (sin colisiones ni ambigüedades), `normalize` (espacios y, si se pide,
  mayúsculas; sin tildes ni tipos), `replace` (mapa exacto, `unknown` keep/exclude/error).
- Recetas: `completar` (referencia por clave; completadas, sin_coincidencia, ambiguas,
  clave_vacia; nunca multiplica filas ni pisa datos sin `existentes`), `duplicados` (idénticas,
  conflictos, conservar primero/ultimo/mas_reciente explícito, empate = conflicto) y entradas
  con `fila_encabezado` y `excluir_filas` (fila real conservada).
- Todo deja cambios, excluidas y procedencia en la traza, e invariantes por paso.
- Compatibilidad: `consultar` suelto recupera su salida de 1.4.1. **Cambios deliberados**:
  claves JSON repetidas en planes, reglas y recetas son error (antes ganaba la última); en la
  vista previa un encabezado ilegible es error (antes aviso). `transformar` suelto avisa
  (código 1) solo si un plan usa `replace` con `unknown: keep`.

## Cambios de 1.5.0-etapa2 (trazabilidad de recetas)

- Procedencia real por fila como metadato interno (`tableio.ORIGEN`, `traza.py`), sin columnas
  nuevas: `<salida>_procedencia.csv`, `excluidas.csv`, `cambios_celdas.csv`, participación en
  agregados y procedencia de comparar. Incidencias y `__fila_origen` citan la fila original.
- Invariantes por paso antes de publicar (partición, participación, claves); si fallan, el
  paso queda `fallido` sin tablas. Manifiesto con conteos, parámetros, trazas y detalles.
- Vista previa y `ejecutar` comprueban columnas leyendo solo encabezados (CSV/XLSX).
- Manual: `tools/ejecutar.md` (sección Trazabilidad).

## Cambios de 1.5.0-etapa1 (recetas)

- `ejecutar ARCHIVO --receta R.json`: pasos existentes en orden, con referencias `paso.salida`,
  políticas por paso (detener por defecto, `separar` en validar/consolidar/entradas, advertencias
  permitidas por código) y `--vista-previa` sin leer datos. Manual: `tools/ejecutar.md`.
- Receta comprobada entera antes de ejecutar; errores con código, paso, campo y sugerencia.
- `manifiesto.json` por ejecución, reescrito de forma atómica: `en_curso`, `completada`,
  `completada_con_incidencias`, `fallida` (con `motivo`).
- Una sola comprobación de planes (`operations.check_plan`) para `transformar` y recetas;
  `consolidar` y recetas comparten `merge_tables`. Ejemplo: `recetas/revision_ordenes.json`.

## Cambios de 1.4.1 (correcciones de `consultar`)

- Salida numérica como texto decimal sin exponente ni redondeo añadido (antes `.12g`:
  `1234567890123` → `1.23456789012e+12`, `0.0000001` → `1e-07`, que `validar` rechazaba).
- Infinitos y entradas no nulas que quedarían en cero: error (código 2) con tabla y columna,
  `FAILED.json` y ninguna tabla publicada (antes `inf` con estado `ok`).
- Más de 15–17 cifras en `--numeric`: advertencia `numeros_redondeados_por_precision_real`.
- Omitir `--numeric` en una columna con decimales cuyo uso cambia el resultado: advertencia
  `resultado_depende_de_texto_sin_numeric` (antes `SUM` de `2,5` y `3,5` daba 5 con `ok`).
- Siguen existiendo: cálculos SQL en punto flotante (no exactos al dígito), sin aviso para
  columnas solo de enteros usadas como texto ni para resultados calculados que se vuelven cero.
  Detalle en `tools/consultar.md`.

## Cambios de 1.4.0

- `consultar`: una sentencia SELECT sobre SQLite en memoria; un autorizador deniega todo lo demás.
- `bitacora`: anotaciones en `data/bitacora/bitacora.csv` (privado, sin respaldo en Git) e informe.
- Regla `allowed` en `validar` (`valor_no_permitido`).
- `examples/minera/` y `docs/EJERCICIOS.md`: datos ficticios con errores inyectados y respuestas
  verificadas; `scripts/datos_mineros.py` los regenera en otra carpeta.

## Cambios de 1.3.0

- El aviso de delimitador trae `sugerencia` (p. ej. `--delimiter ';'`). Errores de
  codificación y de archivo inexistente tienen mensaje propio y accionable.
- Las ejecuciones con `--output` dentro de `tmp/` (pruebas) ya no llenan `logs/`.

## Cambios de 1.2.0

- Lanzadores `./kit` y `kit.cmd`; salida UTF-8 en Windows; `--run-name` rechaza nombres
  reservados de Windows.
- Rendimiento medido con 300 000 filas × 6 columnas (16 MB), antes → después:
  inspeccionar 12 → 2 s, validar 14 → 4,5 s, comparar (1,5 M de cambios) 23 → 13 s,
  consolidar 600 000 filas 11 → 8 s, exportar CSV 1,5 s, exportar con XLSX 28 → 25 s.
  Memoria máxima ≈ 750 MB. XLSX sigue siendo lo lento: usar `--format csv` si no hace falta.
- Tablas JSON de salida con una fila por línea (mismo contenido, menos tamaño).

## Cambios de 1.1.0

- Aviso `posible_delimitador_incorrecto` (código 1) cuando un CSV queda en una sola
  columna cuyo encabezado contiene otro separador. Antes devolvía `ok` en silencio.
- El resumen de terminal incluye `incidencias_por_codigo`, `advertencias_por_codigo`,
  `conteos` y, al inspeccionar, `tablas` con nombres de columnas. Sin valores de celdas
  (desde 1.4.0 la excepción es `consultar`, que muestra filas salvo con `--show 0`).
- `limpiar`: lista o borra (`--apply`) ejecuciones y registros antiguos.
- `logs/` se crea sola: un clon nuevo funciona sin pasos manuales.
- CI en GitHub Actions (`.github/workflows/check.yml`): Linux y Windows.

## Límites vigentes

- Tablas completas en memoria (≈ 2,5 KB por fila en la medición de 300 000 filas; 77–181 MiB y 1,5–30 s
  por comando con 100 000 filas × 5 columnas, `MEDICIONES.md`): no apto para millones de filas. Lo
  lento es escribir XLSX; una receta escribe además cada tabla intermedia y su traza (≈ 8× la entrada).
- No lee XLS/XLSB/ODS ni libros cifrados; no conserva macros, fórmulas ni estilos.
- Sin transacción atómica por carpeta: `FAILED.json` o falta de `report.json` = no usar.
  En recetas, el estado de `manifiesto.json` es atómico; los archivos de cada paso no.
- Recetas: sin carpetas como entrada (consolidar recibe una lista de entradas) y destinos solo
  dentro de la carpeta de ejecución. Las tablas JSON no se comprueban por encabezado en la
  vista previa (habría que leerlas completas).
- Trazabilidad solo en recetas (los comandos sueltos no escriben excluidas ni procedencia).
  Sin procedencia por fila tras `group` ni en resultados SQL; en `excluidas.csv` y
  `cambios_celdas.csv` hay valores de celdas. Los archivos de traza duplican aprox. el número
  de líneas de cada tabla intermedia (una línea por fila).
- `completar` trata cualquier clave repetida de la referencia como ambigua, aunque las filas
  sean idénticas (deduplicar antes). `normalize` no detecta por sí mismo claves unidas: solo
  las cuenta (`valores_unificados`); el choque se ve en `duplicados` o `validar`.
- `replace` con `exclude` en `transformar` suelto no guarda las filas excluidas (como `filter`).
- Esquemas: generados desde el código y vigilados por un corpus; un caso fuera del corpus podría
  divergir. Reglas semánticas (referencias, columnas, archivos…) solo las comprueba el kit.
  Un entero escrito `1.0` es entero para JSON Schema pero el kit lo rechaza.
- El detector de texto numérico es heurístico: no avisa por columnas solo de enteros y puede dar
  falsos positivos; por encima de su límite de filas no se ejecuta (y lo avisa). Declarar tipos.
- Ejemplos y reglas son ficticios; adaptar reglas con quien conozca el proceso real.
- `vendor/` (ruedas offline) es local y solo para Linux/Python 3.14; no está en Git.

Detalle de formatos: `DATA_POLICY.md`. Evidencia histórica de la versión 1.0.0, disco y
verificación offline: `VERIFICATION.md` (no hace falta leerla para trabajar).

## Retomar

Elegir comando en `TOOLS_INDEX.md`, leer solo su manual, usar una ejecución nueva.
Tras cambios de código: `check.py`, `demo.py` si afecta el flujo, y actualizar este archivo.

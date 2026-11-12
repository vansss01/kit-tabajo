# Estado del proyecto

Actualizado: 2026-11-12. Versión 1.5.0-etapa1 (sin commit). Repositorio: `github.com/vansss01/kit-tabajo` (privado).
1.4.1 y 1.5.0-etapa1 están comprobadas **solo en local, Linux, Python 3.14.9**: 57 pruebas, Ruff y
mypy con `scripts/check.py` y flujo `scripts/demo.py`. No están publicadas: la CI (Linux y Windows,
Python 3.11 y 3.14, instalación sin red y lanzadores) corrió por última vez sobre 1.4.0; Windows
queda pendiente hasta el próximo push. Sin dependencia de proveedores de IA.

Comandos: inspeccionar, comparar, consolidar, validar, transformar, exportar, consultar,
ejecutar, bitacora, limpiar.

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

- Tablas completas en memoria (≈ 2,5 KB por fila en la medición): no apto para millones de filas.
- No lee XLS/XLSB/ODS ni libros cifrados; no conserva macros, fórmulas ni estilos.
- Sin transacción atómica por carpeta: `FAILED.json` o falta de `report.json` = no usar.
  En recetas, el estado de `manifiesto.json` es atómico; los archivos de cada paso no.
- Recetas: sin carpetas como entrada (consolidar recibe una lista de entradas), destinos solo
  dentro de la carpeta de ejecución, columnas comprobadas al ejecutar y no en la vista previa.
- Ejemplos y reglas son ficticios; adaptar reglas con quien conozca el proceso real.
- `vendor/` (ruedas offline) es local y solo para Linux/Python 3.14; no está en Git.

Detalle de formatos: `DATA_POLICY.md`. Evidencia histórica de la versión 1.0.0, disco y
verificación offline: `VERIFICATION.md` (no hace falta leerla para trabajar).

## Retomar

Elegir comando en `TOOLS_INDEX.md`, leer solo su manual, usar una ejecución nueva.
Tras cambios de código: `check.py`, `demo.py` si afecta el flujo, y actualizar este archivo.

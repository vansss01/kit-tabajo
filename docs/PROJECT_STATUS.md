# Estado del proyecto

Actualizado: 2026-11-10. Versión 1.3.0. Repositorio: `github.com/vansss01/kit-tabajo` (privado).
Comprobado en Linux y Windows (Python 3.11 y 3.14) por CI en cada cambio: 36 pruebas,
Ruff y mypy con `scripts/check.py`, flujo `scripts/demo.py`, instalación sin red y
lanzadores `kit`/`kit.cmd`. Sin dependencia de proveedores de IA.

Comandos: inspeccionar, comparar, consolidar, validar, transformar, exportar, limpiar.

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
  `conteos` y, al inspeccionar, `tablas` con nombres de columnas. Sin valores de celdas.
- `limpiar`: lista o borra (`--apply`) ejecuciones y registros antiguos.
- `logs/` se crea sola: un clon nuevo funciona sin pasos manuales.
- CI en GitHub Actions (`.github/workflows/check.yml`): Linux y Windows.

## Límites vigentes

- Tablas completas en memoria (≈ 2,5 KB por fila en la medición): no apto para millones de filas.
- No lee XLS/XLSB/ODS ni libros cifrados; no conserva macros, fórmulas ni estilos.
- Sin transacción atómica por carpeta: `FAILED.json` o falta de `report.json` = no usar.
- Ejemplos y reglas son ficticios; adaptar reglas con quien conozca el proceso real.
- `vendor/` (ruedas offline) es local y solo para Linux/Python 3.14; no está en Git.

Detalle de formatos: `DATA_POLICY.md`. Evidencia histórica de la versión 1.0.0, disco y
verificación offline: `VERIFICATION.md` (no hace falta leerla para trabajar).

## Retomar

Elegir comando en `TOOLS_INDEX.md`, leer solo su manual, usar una ejecución nueva.
Tras cambios de código: `check.py`, `demo.py` si afecta el flujo, y actualizar este archivo.

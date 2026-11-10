# Estado del proyecto

Actualizado: 2026-11-10. Versión 1.1.0. Repositorio: `github.com/vansss01/kit-tabajo` (privado).
Implementado y comprobado en Linux (Python 3.14): 35 pruebas, Ruff y mypy OK con
`scripts/check.py`; flujo completo con `scripts/demo.py`. Sin dependencia de proveedores de IA.

Comandos: inspeccionar, comparar, consolidar, validar, transformar, exportar, limpiar.

## Cambios de 1.1.0

- Aviso `posible_delimitador_incorrecto` (código 1) cuando un CSV queda en una sola
  columna cuyo encabezado contiene otro separador. Antes devolvía `ok` en silencio.
- El resumen de terminal incluye `incidencias_por_codigo`, `advertencias_por_codigo`,
  `conteos` y, al inspeccionar, `tablas` con nombres de columnas. Sin valores de celdas.
- `limpiar`: lista o borra (`--apply`) ejecuciones y registros antiguos.
- `logs/` se crea sola: un clon nuevo funciona sin pasos manuales.
- CI en GitHub Actions (`.github/workflows/check.yml`): Linux y Windows.

## Límites vigentes

- Tablas completas en memoria; sin benchmark para archivos masivos.
- No lee XLS/XLSB/ODS ni libros cifrados; no conserva macros, fórmulas ni estilos.
- Sin transacción atómica por carpeta: `FAILED.json` o falta de `report.json` = no usar.
- Ejemplos y reglas son ficticios; adaptar reglas con quien conozca el proceso real.
- `vendor/` (ruedas offline) es local y solo para Linux/Python 3.14; no está en Git.

Detalle de formatos: `DATA_POLICY.md`. Evidencia histórica de la versión 1.0.0, disco y
verificación offline: `VERIFICATION.md` (no hace falta leerla para trabajar).

## Retomar

Elegir comando en `TOOLS_INDEX.md`, leer solo su manual, usar una ejecución nueva.
Tras cambios de código: `check.py`, `demo.py` si afecta el flujo, y actualizar este archivo.

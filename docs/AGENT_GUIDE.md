# Instrucciones comunes para cualquier agente

1. Este es un kit Python local, independiente de IA. No instalar agentes, MCP,
   servidores, extensiones, Docker ni servicios de pago para usarlo. Única excepción (desde
   1.6.0-interfaz1): `./kit interfaz`, un servidor HTTP local de la biblioteca estándar que escucha
   solo en 127.0.0.1, exige un token por sesión, vive en `src/kitlib/interfaz/` (el núcleo no lo
   importa) y se cierra con Ctrl+C. Sin dependencias, Node, CDN ni recursos externos. Como agente,
   usa la CLI; la interfaz es para personas. Límites: `tools/interfaz.md`.
2. Lee `TOOLS_INDEX.md` para elegir una herramienta. Consulta solo el manual
   pertinente. Usa `python -B kit.py SUBCOMANDO --help` antes de reescribir código.
   Para saber qué admite el kit sin leer código: `./kit catalogo` (JSON). Antes de ejecutar una
   receta, plan o reglas que escribiste: `./kit comprobar ARCHIVO --json` (solo configuración);
   esquemas en `schemas/`, códigos en `CODIGOS.md`. Para leer una ejecución: `./kit resultados`.
   Con datos sensibles añade `--ocultar-valores` (ver la tabla de `DATA_POLICY.md`).
   Antes de escribir una receta nueva, parte de una de `recetas/` (tres de ejemplo, con entradas en
   `examples/recetas/` y resultados esperados en archivos aparte en `examples/recetas/esperados/`).
3. Lanzador sin activar nada: `./kit COMANDO ...` en Linux, `kit COMANDO ...` en Windows
   (`kit.cmd`, usa `.venv-win`). Equivale a `python -B kit.py` con el Python local.
4. Todas las escrituras controladas deben quedar dentro de KIT TABAJO en el disco
   de datos. No fijar su punto de montaje en código. `kitlib.runtime.ROOT` lo descubre
   desde el módulo. Antes de cambiar de ubicación verifica disco y permisos reales;
   no crear una carpeta homónima en el SSD, modificar montajes ni escribir fuera.
5. Nunca sobrescribir originales ni salidas. Usar carpetas exclusivas de ejecución.
   `limpiar --apply` borra resultados: solo si el usuario lo pide expresamente.
   No ejecutar código de planes, fórmulas ni celdas. No enviar tablas a servicios.
6. Separar inspección, validación y transformación. Preservar códigos y ceros;
   pedir formato explícito si una fecha es ambigua. Revisar código de salida:
   0 correcto, 1 incidencias/advertencias, 2 error. No tratar 1 como éxito total.
   En `ejecutar`, revisar `manifiesto.json`: solo `completada*` es un flujo terminado.
   Usar `--vista-previa` antes de ejecutar una receta nueva; no valida datos. Para explicar
   qué pasó con una fila, leer las `trazas` del paso en el manifiesto; no reconstruir a mano.
   No elegir por el usuario: equivalencias de `replace`, `existentes` de `completar`, `conservar`
   de `duplicados` y `excluir_filas` se escriben solo si quien usa el kit lo decidió; si no, dejar
   los valores por defecto (conservadores) y mostrar conflictos, ambiguas y excluidas.
7. Preferir `--json`: su resumen suele bastar; leer `report.json` selectivamente. No imprimir archivos
   completos, credenciales, valores sensibles ni listados masivos. `--verbose` tiene
   límites; archivos de detalle y registros permanecen locales.
8. No explorar `.venv*`, `.cache`, `.runtime`, `tmp`, `vendor`, `data`, `results`,
   `logs` indiscriminadamente. `.gitignore` NO bloquea lecturas. Entrar solo a la ruta
   concreta necesaria. Los datos reales nunca se agregan al control de versiones.
9. Código compartido en `src/kitlib/`; CLI en `kit.py`. Preferir biblioteca estándar.
   Dependencias fijadas en requirements; documentar cualquier cambio y sus límites.
10. Tras cambios ejecutar `python -B scripts/check.py` (Ruff, mypy, unittest).
    Si afecta al flujo ejecutar también `scripts/demo.py`; si tocaste un bloque con mutaciones,
    `scripts/mutaciones.py NOMBRE`. Corregir fallos antes de declarar terminado. Actualizar
    `PROJECT_STATUS.md` en pocas líneas; no leer `VERIFICATION.md` (evidencia histórica) salvo
    que la tarea lo requiera. No declarar Windows probado sin una CI verde sobre el código actual.

## Dónde está cada respuesta (sin duplicar manuales)

| Pregunta | Dónde |
|---|---|
| Qué significa cada estado de `manifiesto.json` y de un paso | `tools/ejecutar.md` («Resultados y manifiesto»), `CODIGOS.md` |
| Cuándo se detiene una receta y cómo dejar que siga | `tools/ejecutar.md` («Políticas»): sin política, **detener**; `separar` solo en validar, completar, duplicados, consolidar y entradas |
| Qué filas quedaron fuera y dónde están | `tools/ejecutar.md` («Trazabilidad»): `rechazadas.*`, `excluidas.csv`, `conflictos.*`, `sin_coincidencia.*`, `00-entradas/incidencias.csv` |
| Cómo revisar qué cambió en una celda o por qué desapareció una fila | `tools/ejecutar.md` («Revisar un cambio»): `cambios_celdas.csv`, `excluidas.csv`, `*_procedencia.csv`; `./kit resultados NOMBRE --paso P` |
| Validar, transformar o completar desde una fuente: cuál corresponde | abajo, «Tres cosas distintas» |
| Límites numéricos (SQL, REAL, decimales, `1.0`) | `tools/consultar.md` («Números»), `ESQUEMAS.md` |
| Límites de memoria y tiempo medidos | `MEDICIONES.md` (≈ 2,5 KiB por fila en memoria; XLSX es lo lento) |
| Qué salidas contienen valores de celdas y cómo ocultarlos | `DATA_POLICY.md` («Qué salidas pueden contener valores de celdas») |
| Qué código es cada error, incidencia o advertencia | `CODIGOS.md`, `./kit catalogo` |

**Tres cosas distintas.** *Validar* (`validar`, paso `validar`) solo señala: compara cada fila con reglas
y la deja en `aceptadas` o `rechazadas` sin tocar un valor; únicamente `aceptadas` queda marcada
`validada: true`. *Transformar* (`transformar`, paso `transformar`) calcula una tabla nueva a partir de
otra (filtrar, convertir, agrupar, renombrar, normalizar, reemplazar): el resultado no está validado y
cada fila quitada o celda cambiada queda registrada. *Corregir desde una fuente* (paso `completar`)
copia datos de una tabla de referencia por una clave exacta: no inventa valores, no elige entre dos
coincidencias y no pisa un dato presente salvo que `existentes` lo diga. Las tres dejan constancia; ninguna
modifica el archivo original.

No asumir que un agente descubre este archivo automáticamente: README incluye una
instrucción para pegar. No depender de memoria privada ni del historial de una sesión.

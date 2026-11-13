> **Nota de cierre (versión 1.5.1, 13 de noviembre de 2026).** Este es el informe de la auditoría independiente de la
> 1.5.0 (`402bb30`), copiado sin cambios desde `tmp/auditoria-150-cnab304p/AUDITORIA.md`. Cada hallazgo se reprodujo
> antes de corregirlo. Estado en 1.5.1, con el commit que lo cierra:
>
> | Hallazgo | Estado en 1.5.1 | Commit |
> |---|---|---|
> | 1. Errores JSON incompletos (argparse) | Resuelto: con `--json` todos los errores de argumentos salen como `errores` por stdout, código 2; códigos `argumento_ausente`, `argumento_desconocido`, `comando_desconocido`. Sin `--json`, igual que antes. | `d0c6b89` |
> | 2. Ejemplo SQL del reporte con totales NULL | Resuelto: el comando lleva `--decimal ','`; el kit sugiere `--decimal` cuando los NULL serían números con el otro separador (sin convertir por su cuenta); `tests/test_reporte.py` ejecuta los comandos del reporte. Ya daba código 1 y aviso visible: no hubo silencio, faltaba la sugerencia. | `1cd98b8` |
> | 3. Garantías históricas no acreditables | Declarado en `PROJECT_STATUS.md` (esperados sin orden acreditado, sin instantánea 1.4.1, cambio de aviso SQL por encima de 200 000 filas y cómo recuperarlo). Sin cambios de código. | `672c845` |
> | 4. Medición de comparar inválida | Resuelto: generador corregido, comprobación de proporciones que falla si no se cumplen, mediciones repetidas (`MEDICIONES.md` declara la cifra anterior como no válida). | `76195f6` |
> | 5. `test_help_all_commands` no detectaba su rotura | Resuelto: comprueba `usage:` y las opciones de los 13 comandos; reforzada también `test_cli_codes_and_invalid_arguments` (las únicas dos que solo miraban el código de salida). | `7241a27` |
> | 6. Reporte que exagera | Resuelto en texto: `REPORTE_KIT.html` y manuales dicen solo lo verificado (traza completa solo en recetas, sin procedencia tras `group`/SQL, invariantes por paso, REAL no exacto, qué `1.0` se rechaza, esperados «en archivo aparte»). | `b44fcbd` |
>
> Las observaciones de la tabla «Afirmaciones dudosas» se trataron dentro de los hallazgos 2 y 6. La afirmación de la
> línea 232/269 («con `--json` los errores traen código, campo y sugerencia») pasó a ser cierta con el hallazgo 1.

# Auditoría independiente de KIT TABAJO 1.5.0

Revisión de `402bb30`, 13 de noviembre de 2026. Python local 3.14.9, Linux.
No se modificaron originales, código, documentación ni Git. Todas las escrituras de esta auditoría quedaron en
`/mnt/DATA/KIT TABAJO/tmp/auditoria-150-cnab304p/`.
El archivo preexistente y no versionado `examples/con incidencias copia brouski.csv` permanece intacto y sin agregar.

Los scripts se ejecutaron en `actual/`, una extracción idéntica de `git archive HEAD`, porque `configure()` crea
cachés y registros incluso con `--output`. Esto permite respetar la restricción de escribir solo en `tmp/`.
Las versiones antiguas se extrajeron con `git archive`, sin usar worktrees que escribieran metadatos en `.git`.
En los comandos siguientes, `python` representa `/mnt/DATA/KIT TABAJO/.venv/bin/python`.

## Hallazgos, por impacto

1. **Media: contrato de errores JSON incompleto (etapa 4).**
   `python -B kit.py validar 'examples/con incidencias.csv' --json` devuelve código 2, stdout vacío y
   un error textual de argparse por falta de `--rules`; no existe el prometido objeto `errores`.
   Lo mismo ocurre con `consultar ... --show abc --json`.
   `src/kitlib/cli.py:384` llama a `parse_args()` fuera del manejador de errores.
   Evidencia completa: `sondas.json`, casos `error-parser` y `error-tipo-parser`.

2. **Media: el comando SQL de REPORTE_KIT.html produce totales nulos.**
   `python -B kit.py consultar examples/minera/ordenes.csv --delimiter ';' --tipo t.horas=number
   --sql 'SELECT estado, COUNT(*) AS n, SUM(horas) AS horas FROM t GROUP BY estado'`
   devuelve código 1, 598 valores no numéricos y las siete sumas vacías/NULL.
   Agregar `--decimal ','` devuelve código 0, cero valores no numéricos y totales como
   `abierta=973.4` y `cerrada=5407.6`. El archivo tiene 600 filas; las otras dos horas son vacías.
   Evidencia: `sondas.json`, `sql-reporte` y `sql-reporte-corregido`; HTML, líneas 158–161.

3. **Media: faltan pruebas históricas para dos garantías de la etapa 5.**
   No hay commit 1.4.1: `git log --all -p -- src/kitlib/__init__.py` salta de 1.4.0 a 1.5.0-etapa1.
   `git show --no-patch 068e891` dice explícitamente que incorporó las correcciones de 1.4.1 «sin commit previo».
   Por tanto, la comparación exacta con esa versión no es reproducible desde este repositorio.
   Además, `git show --stat 89abf8b` introduce simultáneamente el primer esperado y
   `tests/test_recetas_ejemplo.py`; los otros esperados se introducen después del comprobador, en
   `42ef457` y `1e7f605`. Todas las operaciones ya existían. Git no demuestra que los esperados se
   escribieran antes de ejecutar el kit ni que fueran independientes de su salida. Tampoco demuestra que se copiaran.
   Sus valores sí coinciden con las ejecuciones actuales.

4. **Media: la medición de comparar no ejercita las modificaciones anunciadas.**
   `python -B sondas.py` llama al generador real `scripts/medir.py:generar` con 10 000 filas:
   produce 9 800 anteriores, 200 nuevas y **0 modificadas**, frente al 1 % de modificaciones documentado.
   En `scripts/medir.py:67–68`, todos los múltiplos de 100 quedan excluidos antes por ser múltiplos de 50.
   La cifra de tiempo existe, pero mide altas y filas iguales, no ese escenario de cambios.
   Evidencia: `sondas.json`, `generador-mediciones`.

5. **Baja: una de cinco pruebas aleatorias no detecta una rotura de lo que anuncia cubrir.**
   `python -B -m unittest tests.test_kit.KitTests.test_help_all_commands -v` pasa antes y después de
   sustituir `ArgumentParser.print_help` por una función que no imprime nada: **OK**, código 0, ayuda vacía.
   Solo comprueba el código de salida. Las otras cuatro mutaciones independientes provocan fallos de aserción.
   Evidencia: `mutaciones-azar.json`, `azar-3-mutante.log` y tabla inferior.

6. **Baja: el reporte presenta garantías más amplias que el alcance implementado.**
   La traza por fila no existe en comandos sueltos, ni como procedencia individual después de agrupar o consultar SQL;
   el aviso de precisión no cubre todos los cálculos. La lista completa de afirmaciones dudosas está más abajo.
   Son límites relevantes al usar resultados en procesos reales, aunque parte de ellos sí está documentada en los manuales.

## Ejecuciones obligatorias y recetas

Desde `actual/` se ejecutaron sin modificar los scripts:

| Comando | Resultado | Evidencia |
|---|---|---|
| `python -B scripts/check.py` | Código 0; Ruff y mypy OK; 122 pruebas, OK | `check.log`, `actual/logs/{lint,tipos,pruebas}.log` |
| `python -B scripts/demo.py` | Código 0; flujo completo y hashes verificados | `demo.log` |
| `python -B -u scripts/mutaciones.py` | Código 0; 97/97 detectadas | `mutaciones.log` |

`python -B auditar_cli.py` ejecutó las tres recetas por CLI y comparó independientemente todos los campos de sus
esperados: estados, códigos de salida, conteos por paso y código, columnas completas especificadas, filas clave,
tablas completas especificadas, incidencias y existencia de exportaciones. No importó el comprobador del proyecto.
Resultado: **6 casos, cero diferencias**. La existencia de los XLSX es lo exigido por los esperados; no se confunde
esa comprobación con una comparación exhaustiva del contenido de cada libro.

| Receta | Primera entrada: resultado comprobado | Segunda entrada |
|---|---|---|
| `revision_ordenes` | 3 aceptadas (OT100, OT101, OT108), 7 rechazadas, 7 incidencias; resumen 0007 → 2 órdenes, 3.0 horas | 5 aceptadas, 0 rechazadas; resúmenes 0007=4.0, 0012=6.0, 0042=2.0 |
| `consolidacion_turnos` | 8 unidas, 5 conservadas, OT302 idéntica excluida, OT303 dos veces en conflicto con 1,0 y 3,0 horas; resumen 2.5/3.5/4.5 | 3 conservadas, 1 idéntica excluida, 0 conflictos |
| `enriquecimiento_flota` | OT500, OT501 y OT505 completadas; OT502 sin coincidencia, OT503 ambigua, OT504 clave vacía; 5 incidencias; Agua=3.0, Taller=1.5 | 2 completadas; 2 incidencias por clave duplicada en referencia; Agua=1.0, Taller=2.0 |

Cada comando exacto está guardado en `comandos-recetas.json`; comparaciones y carpetas de salida, en `recetas-cli.json`.
Comando representativo: `python -B kit.py ejecutar examples/recetas/ordenes_semana_1.csv
--receta recetas/revision_ordenes.json --output tmp/auditoria-cli/salidas --run-name revision_ordenes-1 --json`.

## Integridad de originales e historial

Para cada archivo versionado de `examples/`, se obtuvo el primer commit con
`git log --all --reverse --diff-filter=A --format=%H -- ARCHIVO` y se ejecutó
`git diff COMMIT_INICIAL HEAD -- ARCHIVO`, además de `git diff HEAD -- ARCHIVO`.
**31 archivos; 31 diffs vacíos**. Evidencia por archivo: `historial-originales.json`.

Se inspeccionaron los árboles completos de los 36 commits alcanzables mediante
`git rev-list --all` y `git ls-tree -r --name-only COMMIT`.
Ninguno contiene `tmp/`, `results/`, `logs/`, `data/`, `.venv/` ni
`examples/con incidencias copia brouski.csv`. Evidencia: `historial-prohibidos.json`.
El control final SHA-256 no encontró ningún cambio en los archivos originales inventariados antes de la auditoría.
`git status --short` conserva únicamente el CSV no versionado preexistente.

## Cinco pruebas elegidas al azar

Selección reproducible: `random.Random(1704138877876778319).sample(sorted(pruebas), 5)`.
Universo: las 122 funciones de prueba encontradas por AST en `tests/test_*.py`.
Se hizo una extracción nueva de HEAD para cada mutante y se ejecutó la misma prueba antes y después de la rotura.
Todas pasaron antes. Las mutaciones no cambian las pruebas ni producen errores de sintaxis/importación.

| Prueba | Rotura | Resultado mutado |
|---|---|---|
| `tests.test_transformaciones.EncabezadosTests.test_header_row_and_explicit_footers_keep_real_row_numbers` | Numerar datos desde 2 aunque haya títulos | FAIL, aserción de filas |
| `tests.test_kit.KitTests.test_empty_file_and_header_only` | Quitar aviso de archivo con solo encabezado | FAIL, falta `sin_filas_de_datos` |
| `tests.test_kit.KitTests.test_help_all_commands` | Eliminar todo el texto de ayuda | **OK: no detectada** |
| `tests.test_kit.KitTests.test_duplicate_and_empty_keys_block_comparison` | No revisar claves duplicadas/vacías en comparar | FAIL, publica tablas indebidamente |
| `tests.test_transformaciones.RecetaCompletaTests.test_same_recipe_on_two_compatible_files_and_a_failure_midway` | Quitar normalización de espacios | FAIL, la primera receta falla indebidamente |

Ejecutor: `python -B mutaciones_azar.py`. Semilla y universo: `azar.json`. Parches exactos, comandos y códigos:
`mutaciones-azar.json`. Registros: `azar-N-baseline.log`, `azar-N-mutante.log`.

## Privacidad

Se repitieron las tres recetas sin modificar con `--ocultar-valores --verbose`, con salida JSON y textual.
Se buscaron todos los valores no vacíos de las celdas de sus entradas en stdout/stderr, `report.json`,
`manifiesto.json`, `audit.json`, `incidencias.json`, y en `resultados` (resumen, cada paso y cada código de incidencia,
tanto JSON como texto). **162 superficies de salida revisadas; no se encontró una exposición de celdas.**
La coincidencia textual `25` apareció en fechas/horas y en nombres de campos como `sha256`, no como contenido de la celda horas=25.
El registro conserva las coincidencias literales para no ocultar ese falso positivo.
Los archivos de tablas y trazas de cambios sí contienen datos, conforme al alcance documentado de la opción.
Evidencia: `privacidad.json`, `comandos-recetas.json`, archivos `*.stdout` y `*.stderr` en `actual/tmp/auditoria-cli/`.
Este resultado acredita esos ejemplos; no constituye una garantía universal sobre cualquier receta o dato.

## Compatibilidad: diferencias observadas

No existe una instantánea 1.4.1. Se comparó HEAD con `068e891` (primera instantánea con sus correcciones,
ya marcada 1.5.0-etapa1) y adicionalmente con la auténtica 1.4.0, `71ce812`.
Ejecutor: `python -B compatibilidad.py`; casos exactos y salidas en `compatibilidad-ejecuciones.json`;
todos los diffs en `compatibilidad-diferencias.json`. Se usó salida textual predeterminada, sin `--json`/`--verbose`,
y se compararon también todos los archivos CSV y JSON publicados. Se normalizaron solo la raíz de cada copia,
la fecha de ejecución y la versión del audit. Esos metadatos también difieren naturalmente.

Frente a `068e891`:

- `validar`, `transformar`, `consolidar`, `comparar`, `consultar`, consulta sin tipo y consulta de alta precisión:
  mismos códigos, stdout, stderr, filas, incidencias y reportes en los ejemplos ensayados.
- `audit.json` agrega `parametros.ocultar_valores=false` en todos; consultar también agrega
  `tipo=[]`, `detector_texto_numerico="si"`, `detector_max_filas=200000`.
- Plan JSON con `steps` repetida: antes código 0 y tabla, ahora código 2, mensaje `Clave JSON repetida: steps`
  y solo `FAILED.json`. Plan con `filter.value` lista: antes código 0 y tabla vacía, ahora código 2,
  mensaje de valor no escalar y solo `FAILED.json`. Son endurecimientos documentados.
- **Una diferencia adicional de salida por defecto al superar 200 000 filas**:
  `python -B limites.py` consulta SUM(v) sobre 200 001 valores `2,5`, sin declarar tipo.
  Antes: aviso `resultado_depende_de_texto_sin_numeric`, sugerencia `--numeric v`, `columnas_sin_numeric=1`.
  Ahora: aviso `detector_texto_numerico_omitido`, sin esa sugerencia, `columnas_sin_numeric=0`,
  nuevo conteo `detector_omitido_filas=200001`. Ambos devuelven código 1 y la suma textual 400002.
  Cambian terminal, `report.json` y los campos de auditoría indicados. Evidencia: `limites.json`.

Frente a 1.4.0, además de los cambios anteriores:

- Consultar agrega `valores_redondeados` y `columnas_sin_numeric` al detalle del reporte y los conteos de terminal.
- La suma de horas textuales cambia de código 0/sin aviso a 1/con aviso y sugerencia; la suma publicada sigue siendo 3.
  También cambian estado, código y advertencias de `audit.json`, `report.json`, `resumen.csv` y `resumen.json`.
- En la muestra de precisión, salida `1.23456789012e+18` → `1234567890123456800`, código 0 → 1,
  nuevo aviso de precisión. Cambian los mismos informes y también `validos.csv`/`validos.json`.

Estas son todas las diferencias de los casos ejecutados, no una prueba de equivalencia para todo archivo posible.

## Afirmaciones dudosas de REPORTE_KIT.html

| Línea(s) | Afirmación | Evidencia / alcance real |
|---|---|---|
| 60–61, 99, 109, 132, 237 | Constancia de cada fila apartada y cada celda cambiada; nada desaparece | Solo hay traza de ese alcance en recetas. `transformar` suelto ensayado publica tablas e informes, sin excluidas/cambios/procedencia. Además las filas de ancho incorrecto conservan una incidencia y ubicación, no una copia íntegra de sus valores (`tableio.py:220`). |
| 119–125 | Todos los comandos leen, procesan y crean carpeta en results | `catalogo` y `comprobar` no siguen ese flujo; `bitacora` escribe en data; `limpiar` tiene otra finalidad. Se comprueba con el catálogo y las ramas de `cli.main`. |
| 158–161 | Comando SQL de ejemplo para sumar horas | Le falta `--decimal ','`: 598 valores convertidos a NULL y siete totales NULL; reproducción en `sondas.json`. |
| 113, 198–200 | Esperados escritos a mano | No verificable históricamente; primer esperado y comprobador en el mismo commit, los otros posteriores. No se afirma que sean copiados. |
| 246–260 | Cada fila conserva origen; antes de publicar cada paso se verifica entrada=salidas+apartadas | `group` no produce procedencia individual, SQL tampoco; sus invariantes no son esa partición. `traza.invariants` devuelve tipo `ninguna` para SQL y para inspeccionar. El manifiesto real marca el agregado como `sin procedencia individual (agregado)`. |
| 232, 269 | Con `--json` los errores traen código, campo y sugerencia | Los errores del parser no están estructurados; reproducciones `error-parser` y `error-tipo-parser`. |
| 280 | El kit avisa cuando un número no cabe exacto | `SELECT 0.1 + 0.2 AS total` devuelve `0.30000000000000004`, código 0 y cero advertencias. El manual SQL reconoce errores aritméticos sin aviso. |
| 282 | Un entero escrito 1.0 en una configuración se rechaza | Solo corresponde a campos que exigen enteros como sample/version. `comprobar` acepta reglas con `{"type":"number","min":1.0}`: código 0, `valida` (`limites.json`). |
| 286 | Ningún caso del alcance necesita procesamiento distribuido; no sirve para millones de filas | Son decisiones/prudencia de alcance, no un umbral universal demostrado por dos tamaños de medición. Las tablas están en RAM; el máximo depende de columnas, operaciones y equipo. |
| 304–318 | Mediciones atribuidas a versión 1.5.0 | Las cifras coinciden con `tmp/medicion/medicion.json`, pero el registro identifica `1.5.0-etapa4`. El motor desde esa etapa solo cambió de etiqueta de versión, de modo que no es evidencia de cifras inventadas. El defecto del generador limita la interpretación de comparar. |

No se encontraron motivos para cuestionar las cifras de 13 comandos, unas 4 000 líneas (3 996), 122 pruebas o
97 mutaciones. Las nueve filas de la tabla de mediciones coinciden con su registro local, copiado como
`medicion-historica.json` para esta revisión. No se repitió el benchmark completo ni se certificaron físicamente
el modelo de disco y CPU de la medición histórica.

La CI fue verificada directamente mediante
`gh run view 43480431875 --repo vansss01/kit-tabajo --json headSha,conclusion,status,jobs,url`:
`success` sobre `f605d12`, cuatro trabajos success (Linux/Windows × Python 3.11/3.14).
`git diff --stat f605d12 HEAD` solo cambia `docs/PROJECT_STATUS.md` y `docs/REPORTE_KIT.html`.
Por tanto, el código actual sí coincide con el probado en esa CI. Evidencia: `ci-run.json`.

## Etapas 1 a 5: implementado y recortado

No hay un pliego externo de aceptación adjunto a esta revisión; se contrasta con las capacidades y límites
declarados en las guías, el estado y el historial. No se trata una limitación documentada como una función ausente.

| Etapa / requisito | Evaluación |
|---|---|
| 1: recetas, políticas, manifiesto | Implementados y ejercitados por pruebas y ejemplos. Flujo secuencial, sin carpetas como entradas; separar solo en operaciones autorizadas; manifiesto atómico pero archivos del paso sin transacción de carpeta. |
| 2: trazabilidad | Implementada en recetas; limitada en SQL y después de group. Participantes detallados son optativos. Sin trazas de exclusión/cambios en comandos sueltos; consolidar rechazado se identifica por origen y motivos, no publica otra tabla íntegra de rechazados. |
| 3: seis incorporaciones | Presentes `rename`, `normalize`, `replace`, `completar`, `duplicados` y encabezados/pies. No falta ninguna de las seis. Normalize cuenta unificaciones pero no identifica por sí solo conflictos de claves; completar considera ambigua toda clave de referencia repetida, incluso con filas idénticas; encabezados/pies solo CSV/XLSX. Son recortes declarados. |
| 4: esquemas | Publicados/generados y contrastados con un intérprete independiente sobre un corpus. No validan por sí solos las reglas semánticas listadas en ESQUEMAS.md; divergen con enteros JSON escritos 1.0. No se puede generalizar el corpus a equivalencia universal. |
| 4: catálogo | Los 13 comandos y operaciones aparecen; generación desde parser/tablas. Sin carencia observada en el alcance revisado. |
| 4: errores estructurados | Incompleto para errores de argparse; hallazgo reproducido. |
| 4: SQL y privacidad | Tipos explícitos y consultas de lectura implementados. REAL no es decimal exacto; detector heurístico, no cubre columnas solo enteras y se omite por defecto sobre 200 000 filas. Privacidad pasó en los ejemplos auditados, no equivale a una certificación universal. |
| 5: ejemplos, compatibilidad, mediciones | Ejemplos pasan 6/6, pero la independencia histórica de los esperados no está acreditada y falta la instantánea 1.4.1. Medición reproducible de un tamaño moderado, con defecto en las modificaciones generadas; no es benchmark de gran escala. Una prueba débil en la muestra independiente. |

Veredicto: listo con reservas.

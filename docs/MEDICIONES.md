# Mediciones de tiempo, tamaño de salidas y memoria

Cifras de **un** equipo y **un** tamaño de entrada, obtenidas con `scripts/medir.py`. Sirven para saber qué
esperar con una planilla mediana y para notar si una versión futura se vuelve mucho más lenta. **No son una
garantía general**: otro disco, otro Python, otras columnas u otra cantidad de incidencias cambian los números.

## Cómo se midió

```bash
python -B scripts/medir.py                      # 100 000 filas, 3 repeticiones, semilla 2026 → tmp/medicion/
python -B scripts/medir.py --filas 20000 --repeticiones 5 --salida tmp/medicion-chica
```

- El script genera con semilla fija órdenes ficticias con las columnas de `examples/reglas.json`
  (`orden;equipo;fecha;horas;estado`, delimitador `;`, decimal `,`): un archivo completo, el mismo
  repartido en 4 turnos y una versión «anterior» a la que le faltan el 2 % de las filas (múltiplos de 50) y
  el 1 % cambia de horas (filas 25, 125, 225…). Una de cada 1000 filas trae `horas = 25,0` para que `validar`
  encuentre incidencias reales. Antes de medir, el script **comprueba** que el conjunto generado tenga esas
  proporciones exactas (nuevas, eliminadas, modificadas, fuera de rango) y se detiene si no (desde 1.5.1).
- Cada comando se ejecuta en un proceso nuevo, con `--json`, en una carpeta de salida propia. Se mide
  el tiempo de pared del proceso completo (incluye arrancar Python e importar el kit), el tamaño de la
  carpeta de resultados y la memoria máxima del proceso (`ru_maxrss` del hijo, vía `resource`; en
  Windows no existe y queda `null`).
- Los datos generados **no se commitean** (viven en `tmp/`); el script sí. `medicion.json` y
  `medicion.md` quedan junto a los datos.

## Resultado del 2026-11-13 (versión 1.5.1, Linux)

Equipo: portátil con AMD Ryzen 7 4800H (8 núcleos / 16 hilos), 15 GiB de RAM; el proyecto y las
salidas están en un **disco duro mecánico** NTFS (WDC WD10SPZX, 1 TB) montado en `/mnt/DATA`, no en el
SSD del sistema. Linux 7.3.3 (CachyOS), Python 3.14.9, kit 1.5.1, semilla 2026. Entrada: 100 000 filas × 5
columnas (3,7 MiB), 4 archivos de turno de 25 000 filas; 3 repeticiones por comando; el equipo estaba sin
otra carga (en la medición de 1.5.0 corría otro proceso del kit en paralelo). Conjunto comprobado: 2 000
nuevas, 0 eliminadas, 1 000 modificadas, 100 horas fuera de rango.

| Comando | Código | Segundos (mediana / mín / máx) | Memoria máx. (MiB) | Salida (KiB) |
|---|---|---|---|---|
| inspeccionar | 0 | 1,27 / 1,26 / 1,27 | 93 | 4 |
| validar (`--rules examples/reglas.json`, 100 incidencias) | 1 | 1,36 / 1,33 / 1,38 | 101 | 13 929 |
| comparar (`--key orden`, 2 000 nuevas, 1 000 modificadas, 97 000 sin cambios) | 0 | 1,24 / 1,21 / 1,46 | 154 | 416 |
| consolidar (4 archivos) | 0 | 1,32 / 1,30 / 1,35 | 106 | 31 476 |
| transformar (`examples/plan.json`: filtro + grupo) | 0 | 0,68 / 0,67 / 0,69 | 99 | 8 |
| consultar (`GROUP BY equipo`, `--tipo t.horas=number`, `--show 0`) | 0 | 0,86 / 0,84 / 0,87 | 95 | 7 |
| exportar `--format csv` | 0 | 0,54 / 0,54 / 0,55 | 76 | 3 867 |
| exportar `--format xlsx` | 0 | 7,39 / 7,23 / 7,40 | 82 | 2 434 |
| ejecutar `recetas/revision_ordenes.json` (4 pasos, con XLSX y trazas) | 1 | 12,93 / 12,93 / 12,97 | 181 | 31 353 |

**La cifra de comparar publicada en 1.5.0 (2,37 s, 281 KiB) no era válida como medida del escenario anunciado.**
El generador aplicaba el 1 % de modificaciones a las filas múltiplo de 100, que ya había excluido por ser
múltiplo de 50: el conjunto tenía 2 000 nuevas y **0 modificadas**, así que aquel tiempo medía altas y filas iguales
(lo detectó la auditoría independiente de la 1.5.0, hallazgo 4). Con el generador corregido, `report.json` de la
medición confirma `nuevos=2000, eliminados=0, modificados=1000, campos_cambiados=1000`; la salida crece de 281 a
416 KiB porque ahora sí hay cambios que escribir. Las demás mediciones no dependían de ese defecto (las incidencias
de `validar` vienen de las filas múltiplo de 1000; `consolidar` usa los 4 turnos completos).

Las cifras de 1.5.1 son alrededor de la mitad de las de 1.5.0 en todos los comandos (p. ej. inspeccionar 2,95 → 1,27
s; XLSX 12,85 → 7,39 s; receta 30,03 → 12,93 s). El código de los comandos no cambió entre ambas: la diferencia es
del entorno (sin otro proceso del kit en paralelo y con el archivo ya en caché de disco). Por eso las dos series no
son comparables entre sí y la que vale como referencia es esta, repetible con la misma semilla. Memorias y tamaños
de salida coinciden con la medición anterior, como se esperaba. La medición de 1.5.0 queda registrada en
`PROJECT_STATUS.md` y en la auditoría solo como historia.

Qué se desprende, **para este tamaño**:

- Un comando suelto sobre 100 000 filas tarda entre 0,5 y 1,4 s en esta medición (1,5 a 5 s en la de 1.5.0, con el
  equipo cargado); de eso, unos 0,3–0,5 s son arrancar Python.
- Escribir **XLSX** es lo más caro (≈ 7–13 s para 100 000 filas según la carga del equipo): con tablas grandes usar
  `--format csv` o quitar `xlsx` de `formatos` en la receta si el Excel no hace falta.
- La **receta** completa cuesta más que la suma de sus comandos porque escribe cada tabla intermedia en
  CSV y JSON, sus archivos de procedencia (una línea por fila) y el Excel final: 30 MiB de salida para
  3,7 MiB de entrada. Es el precio de la trazabilidad; `limpiar --apply` recupera el espacio.
- La memoria máxima fue 181 MiB (receta) y 154 MiB (comparar, dos tablas en memoria). Con la medición
  de 1.2.0 (300 000 filas × 6 columnas ≈ 750 MiB) la regla práctica sigue siendo **≈ 2,5 KiB por fila
  en memoria** para estas columnas y operaciones; el máximo real depende de la RAM del equipo. Millones de
  filas no caben en este diseño; no se añade procesamiento distribuido por una decisión de alcance
  (planillas de este tamaño), no porque se haya demostrado un umbral.
- `consolidar` y `validar` producen salidas grandes porque publican las tablas completas (CSV y JSON);
  son copias de los datos, con el mismo cuidado que los originales (`DATA_POLICY.md`).

Para repetir la medición en otro equipo o versión, correr el script con la misma semilla y comparar
tabla con tabla; una diferencia de ±30 % en tiempos entre corridas es normal en un disco mecánico.

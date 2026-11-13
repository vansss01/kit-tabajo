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
  repartido en 4 turnos y una versión «anterior» a la que le faltan el 2 % de las filas y el 1 % cambia
  de horas. Una de cada 1000 filas trae `horas = 25,0` para que `validar` encuentre incidencias reales.
- Cada comando se ejecuta en un proceso nuevo, con `--json`, en una carpeta de salida propia. Se mide
  el tiempo de pared del proceso completo (incluye arrancar Python e importar el kit), el tamaño de la
  carpeta de resultados y la memoria máxima del proceso (`ru_maxrss` del hijo, vía `resource`; en
  Windows no existe y queda `null`).
- Los datos generados **no se commitean** (viven en `tmp/`); el script sí. `medicion.json` y
  `medicion.md` quedan junto a los datos.

## Resultado del 2026-11-13 (versión 1.5.0, Linux)

Equipo: portátil con AMD Ryzen 7 4800H (8 núcleos / 16 hilos), 15 GiB de RAM; el proyecto y las
salidas están en un **disco duro mecánico** NTFS (WDC WD10SPZX, 1 TB) montado en `/mnt/DATA`, no en el
SSD del sistema. Linux 7.3.3 (CachyOS), Python 3.14.9, kit 1.5.0. Entrada: 100 000 filas × 5 columnas
(3,7 MiB), 4 archivos de turno de 25 000 filas; 3 repeticiones por comando; otro proceso del kit
corría en paralelo durante parte de la medición (puede inflar algo los máximos).

| Comando | Código | Segundos (mediana / mín / máx) | Memoria máx. (MiB) | Salida (KiB) |
|---|---|---|---|---|
| inspeccionar | 0 | 2,95 / 2,52 / 3,44 | 92 | 4 |
| validar (`--rules examples/reglas.json`, 100 incidencias) | 1 | 5,06 / 4,92 / 5,17 | 100 | 13 928 |
| comparar (`--key orden`, 98 000 filas en común) | 0 | 2,37 / 2,33 / 3,07 | 154 | 281 |
| consolidar (4 archivos) | 0 | 4,72 / 4,05 / 6,64 | 105 | 30 694 |
| transformar (`examples/plan.json`: filtro + grupo) | 0 | 1,56 / 1,23 / 1,69 | 99 | 8 |
| consultar (`GROUP BY equipo`, `--tipo t.horas=number`, `--show 0`) | 0 | 2,28 / 2,07 / 2,91 | 95 | 7 |
| exportar `--format csv` | 0 | 1,50 / 1,44 / 2,27 | 77 | 3 867 |
| exportar `--format xlsx` | 0 | 12,85 / 10,03 / 16,26 | 82 | 2 434 |
| ejecutar `recetas/revision_ordenes.json` (4 pasos, con XLSX y trazas) | 1 | 30,03 / 29,39 / 31,19 | 181 | 30 863 |

Qué se desprende, **para este tamaño**:

- Un comando suelto sobre 100 000 filas tarda entre 1,5 y 5 s; de eso, unos 0,5 s son arrancar Python.
- Escribir **XLSX** es lo más caro (≈ 13 s para 100 000 filas): con tablas grandes usar `--format csv`
  o quitar `xlsx` de `formatos` en la receta si el Excel no hace falta.
- La **receta** completa cuesta más que la suma de sus comandos porque escribe cada tabla intermedia en
  CSV y JSON, sus archivos de procedencia (una línea por fila) y el Excel final: 30 MiB de salida para
  3,7 MiB de entrada. Es el precio de la trazabilidad; `limpiar --apply` recupera el espacio.
- La memoria máxima fue 181 MiB (receta) y 154 MiB (comparar, dos tablas en memoria). Con la medición
  de 1.2.0 (300 000 filas × 6 columnas ≈ 750 MiB) la regla práctica sigue siendo **≈ 2,5 KiB por fila
  en memoria**: millones de filas no caben en este diseño, y no se añade procesamiento distribuido
  porque ningún caso de este alcance lo necesita.
- `consolidar` y `validar` producen salidas grandes porque publican las tablas completas (CSV y JSON);
  son copias de los datos, con el mismo cuidado que los originales (`DATA_POLICY.md`).

Para repetir la medición en otro equipo o versión, correr el script con la misma semilla y comparar
tabla con tabla; una diferencia de ±30 % en tiempos entre corridas es normal en un disco mecánico.

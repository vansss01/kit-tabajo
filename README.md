# KIT TABAJO

Kit personal de terminal para una primera práctica de Ingeniería en Computación.
Procesa archivos y tablas localmente. Funciona sin IA, cuentas, API keys ni servicios
pagados. Codex, Claude Code u otro agente pueden usar los mismos comandos.

## Comenzar en este computador

Ubicación comprobada: `/mnt/DATA/KIT TABAJO`, en DATA (`/dev/sda1`, NTFS),
disco Western Digital de 931,5 GiB. No está en el SSD Samsung del sistema.
El nombre **KIT TABAJO** es intencional.

```bash
cd '/mnt/DATA/KIT TABAJO'
source ./env.sh
python -B kit.py --help
python -B kit.py inspeccionar 'examples/entradas/turno A.csv' --delimiter ';' --decimal ','
python -B scripts/demo.py
python -B scripts/check.py
```

`source ./env.sh` activa el entorno y configura cachés y temporales locales.
También puedes usar `.venv/bin/python -B kit.py ...` sin activar: la entrada configura
las rutas antes de importar las bibliotecas de trabajo. Los resultados indican su
carpeta por terminal. El registro final de la demo está dentro de su última ejecución.
No se escriben modificaciones en el proyecto Expo desde el que se solicitó este kit.

## Instalación y reconstrucción

Requisito: Python **3.11 o posterior**, con `venv` y `ensurepip` disponibles. Se verificó
Python 3.14.9 en Linux. Python y los comandos del sistema ya existían; no se instalaron
herramientas globales. El kit usa la biblioteca estándar, openpyxl 3.1.5, et-xmlfile 2.0.0
y defusedxml 0.7.1. Ruff y mypy solo son necesarios para desarrollo.

Desde la carpeta del kit:

```bash
python3 -B scripts/setup.py --offline --dev
source ./env.sh
python -B scripts/check.py
```

`requirements.txt` fija dependencias de ejecución; `requirements-dev.lock` fija todas
las de desarrollo, incluidas las transitivas. `vendor/` contiene ruedas descargadas
para reinstalar sin red en el Linux/Python comprobado. Sin `--dev` se instalan solo
las dependencias de ejecución, cuyas ruedas son Python puro. Si falta una rueda para
otra plataforma, `python3 -B scripts/setup.py --dev` permite descargarla de PyPI:
solo envía solicitudes de paquetes, nunca tus tablas. La operación normal del kit no
accede a la red. `logs/setup.log` guarda el registro de instalación.

Los entornos virtuales **no son portátiles** entre sistemas ni al cambiar su ruta.
Después de mover el proyecto, renombra el entorno antiguo y reconstruye uno local.
No copies un entorno Linux para ejecutarlo en Windows.

En PowerShell, desde la carpeta situada en el disco de datos:

```powershell
py -3 -B scripts/setup.py --offline
& '.\.venv-win\Scripts\python.exe' -B kit.py --help
& '.\.venv-win\Scripts\python.exe' -B scripts/demo.py
```

El script crea `.venv-win` separado. No requiere cambiar la política de ejecución de
PowerShell. Windows no se probó en esta sesión; no se promete compatibilidad de las
ruedas de desarrollo Linux con Windows. En Windows se usan los mismos CSV/JSON/XLSX.

## Herramientas

| Subcomando | Uso |
|---|---|
| `inspeccionar` | Hojas, columnas, tipos inferidos, filas, vacíos, duplicados y muestra |
| `comparar` | Registros nuevos, eliminados y campos modificados por clave compuesta |
| `consolidar` | Une archivos compatibles y añade archivo/fila de procedencia |
| `validar` | Columnas, vacíos, unicidad, tipos, fechas y rangos mediante JSON |
| `transformar` | Selección, filtros, orden, agrupación, conversión y deduplicación explícitas |
| `exportar` | CSV, JSON y XLSX con resultados, incidencias y resumen separados |
| `limpiar` | Lista o borra (`--apply`) ejecuciones y registros antiguos |

Lee [el índice compacto](docs/TOOLS_INDEX.md) y solo el manual de la herramienta
necesaria. `python -B kit.py SUBCOMANDO --help` describe sus opciones.

Opciones comunes: `--delimiter ';'`, `--encoding cp1252`, `--decimal ','`,
`--date-format '%d/%m/%Y'`, `--sheet 'Órdenes'`, `--json`, `--verbose`.
Todas las opciones se colocan **después del subcomando**. Usa comillas en rutas con
espacios. No hay detección automática de delimitador/codificación ni de fecha regional;
si un CSV queda en una sola columna se avisa con `posible_delimitador_incorrecto`.

## Resultados y códigos de salida

Cada operación crea `results/FECHA-comando-identificador/`. Allí quedan `report.json`
(detalle), `audit.json` (parámetros y huellas), las tablas resultantes y las incidencias.
Los exportadores producen hojas/archivos `validos`, `invalidos`, `incidencias` y `resumen`.
Sin reglas, `validos` solo significa legible estructuralmente; no validado semánticamente.
La comparación genera `nuevos`, `eliminados` y `cambios`.

| Código | Significado |
|---|---|
| 0 | Operación completada sin incidencias ni advertencias |
| 1 | Operación completada con incidencias o advertencias; revisar informe |
| 2 | Error de configuración, argumentos, lectura o ejecución; no usar salidas parciales |

Un código 1 puede contener resultados parciales válidos: por ejemplo, consolidación
con un archivo rechazado o validación con filas inválidas. **No equivale a éxito total**.
Las claves duplicadas/vacías bloquean toda la comparación. Un `FAILED.json` marca una
ejecución fallida; no reutilices sus tablas. No se reemplaza ningún resultado existente.
`--run-name nombre` permite elegir un nombre exclusivo y falla si ya existe.
`--output` solo admite carpetas **dentro del proyecto**, incluso tras resolver enlaces.

La salida normal es compacta. `--json` entrega un único objeto resumen en stdout;
incluye conteos por código de incidencia y nombres de columnas, nunca valores de celdas.
`--verbose` agrega detalle acotado. La ayuda y los errores de sintaxis de argparse son
texto y usan el código 2. Los detalles completos se consultan en los archivos.

## Integridad y límites

CSV se lee como texto: `0007` continúa siendo `0007`. Inspeccionar y validar no convierten
las celdas. Las reglas interpretan números/fechas sin alterar los valores. Nunca se
adivina si `03/04/2026` es marzo o abril. El formato de fecha predeterminado es ISO.
No se admiten separadores de miles ni números exponenciales para reglas numéricas.
Las conversiones y deduplicación solo ocurren mediante pasos explícitos del plan.

Excel se exporta como **libro nuevo de datos**, sin conservar macros, estilos del original,
gráficos ni vínculos. Las fórmulas se leen como texto y no se calculan; XLSX de salida las
escribe como texto. Los códigos guardados numéricamente por Excel ya pueden haber
perdido ceros o precisión: no se reconstruyen silenciosamente. Consulta
[los detalles de formatos e integridad](docs/DATA_POLICY.md).

Las operaciones completas mantienen tablas en memoria: usar archivos que quepan en
RAM. La inspección admite `--limit`, con conteos exactos solo de su alcance, sin estimar
el total. El cálculo SHA-256 siempre recorre el archivo completo. No se afirma que sea
una solución para conjuntos masivos ni una herramienta certificada para procesos críticos.

## Discos, privacidad y exploración

Código, entornos, paquetes, cachés, temporales, ejemplos, pruebas, registros y resultados
quedan dentro de este proyecto. `logs/storage.json` documenta el disco comprobado al
crearlo. No se formateó, reparticionó ni cambió ningún montaje. NTFS permitió ejecutar
el Python copiado, crear enlaces para pruebas y usar nombres UTF-8 con espacios.

El kit no puede controlar los archivos internos del agente, del sistema operativo,
antivirus, historial de la terminal o registros administrativos. No configura el usuario
ni promete ausencia total de escrituras del sistema. Antes de usar otra herramienta que
escriba fuera de esta ubicación, confirma su limitación y configura sus rutas.

`.gitignore` no impide lecturas. Al explorar, **evita** `.venv*`, `.cache`, `.runtime`,
`tmp`, `vendor`, `data`, `results` y `logs`; pueden contener datos sensibles o mucho ruido.
Entra en una ruta concreta solo cuando la tarea lo requiera. Los ejemplos son ficticios.
Los registros contienen rutas, parámetros, tamaños y hashes, pero no vuelcan filas.
Resultados, muestras y diferencias sí pueden contener valores sensibles.

## Continuidad entre agentes

Pega esta instrucción al agente que elijas:

> Trabaja en la carpeta KIT TABAJO del disco de datos. Lee primero docs/AGENT_GUIDE.md,
> docs/TOOLS_INDEX.md y docs/PROJECT_STATUS.md. Reutiliza la CLI existente; consulta solo
> el manual necesario y ejecuta scripts/check.py tras cambios de código.

La documentación del proyecto es suficiente: no requiere memoria privada, historial
ni configuración externa de ningún proveedor. [Estado y límites](docs/PROJECT_STATUS.md);
[evidencia de verificación de la versión 1.0.0](docs/VERIFICATION.md).

En un clon nuevo desde GitHub no existe `vendor/`: usa `python3 -B scripts/setup.py --dev`
(descarga los paquetes fijados de PyPI) en lugar de `--offline`.

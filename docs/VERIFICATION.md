# Evidencia de verificación de la versión 1.0.0 (histórico)

Estado vigente: `PROJECT_STATUS.md`. Este archivo no se actualiza.

Actualizado: 2026-11-10 13:55 UTC.
Versión del kit: 1.0.0. Proyecto implementado y comprobado en Linux; sin integración
ni dependencia de proveedores de IA. No hay tareas funcionales obligatorias pendientes
dentro del alcance implementado descrito aquí.

## Ubicación comprobada

- `/mnt/DATA/KIT TABAJO`, disco DATA, `/dev/sda1`, UUID `4636602C36601EE5`.
- Disco Western Digital WDC WD10SPZX-21Z10T0, 931,5 GiB; NTFS mediante fuseblk.
- Se verificó mismo dispositivo que `/mnt/DATA` y distinto del dispositivo de `/home/vans`.
- Montaje real rw, sin noexec; se probaron ejecución del venv copiado, nombres Unicode,
  rutas con espacios, creación exclusiva, enlaces simbólicos y temporales locales.
- El sandbox del agente presentaba DATA como solo lectura. Las escrituras se realizaron
  con autorización para salir del sandbox, siempre dirigidas al kit. No se alteraron
  particiones ni montajes. El proyecto Expo de origen quedó fuera del alcance de edición.
- Evidencia: `logs/storage.json`, `logs/final_verification.json`.

## Implementación

| Herramienta | Estado comprobado |
|---|---|
| Inspector | CSV/XLSX/XLSM y tablas JSON; hojas, columnas, tipos, vacíos, duplicados, muestras y alcance explícito |
| Comparador | Clave simple/compuesta, bloqueo ante claves vacías/duplicadas, altas/bajas/cambios por campo |
| Consolidador | Columnas compatibles incluso reordenadas, procedencia, rechazos y exclusión de resultados |
| Validador | JSON: columnas, vacíos, unicidad simple/compuesta, tipos, fechas y rangos; sin mutación |
| Transformador | Plan limitado: select/filter/sort/group/convert/deduplicate; sin código ejecutable |
| Exportador | CSV, JSON y XLSX con hojas, filtros, encabezados y anchos; válidos/invalidos/incidencias/resumen |

Todas usan CLI con ayuda, resumen humano/JSON, detalle acotado, códigos 0/1/2 y
salidas exclusivas. Auditoría de parámetros, versiones, archivos y hashes sin filas.
Los manuales documentan semántica y límites; no se promete inferencia automática perfecta.

## Verificación ejecutada

- `python -B scripts/check.py`: **32 pruebas OK**, Ruff OK, mypy OK.
- Registros: `logs/pruebas.log`, `logs/lint.log`, `logs/tipos.log`.
- Casos: archivos CSV/Excel vacíos, encabezados inválidos, columnas faltantes, filas
  mal formadas, claves compuestas/duplicadas/vacías, ceros iniciales, fechas ambiguas,
  formatos heredados en rangos, delimitadores/decimales/codificaciones, JSON null,
  estructuras incompatibles/reordenadas, rutas con espacios y protección de salida.
- También: hashes intactos, muestras sin estimaciones, operaciones declarativas,
  rechazo de código arbitrario, precisión de sumas grandes, filtros/orden numéricos,
  conversiones explícitas, exportación con separación de incidencias, fórmulas inertes,
  avisos de códigos numéricos Excel, límites de celda y señalización de fallos.
- `python -B scripts/demo.py`: flujo completo con aserciones, repetido tras correcciones.
  3 equipos ficticios; 4 órdenes consolidadas. Validación: 1 válida y 2 inválidas.
  Comparación: 2 nuevas, 1 eliminada, 1 modificada, 1 sin cambios, 1 campo cambiado.
  Transformación de órdenes abiertas: equipo 0007 → 2 órdenes/5.5 horas;
  equipo 0042 → 1 orden/4.0 horas. Originales SHA-256 intactos.
- Evidencia del último flujo: `results/20261110T135526Z-exportar-85e704bda5/demo_verificada.json`.
- `python -B scripts/verify_offline.py`: entorno nuevo en tmp/, instalación completa
  sin índice de red desde vendor/, versiones idénticas al lock, pip check y CLI OK.
  Evidencia: `logs/offline_verificado.json`, `logs/offline.log`.
- `python3 -B scripts/setup.py --offline --dev`: script de reconstrucción ejecutado OK.
- Activación `source env.sh` y `kit.py --version` verificadas.
- 10 ruedas guardadas; manifiesto SHA-256 en `vendor/manifest.json`.

## Versiones

Python 3.14.9, Linux. Dependencias de ejecución: openpyxl 3.1.5,
et-xmlfile 2.0.0, defusedxml 0.7.1. Desarrollo: Ruff 0.17.4, mypy 2.4.1.
Lista completa y transitivas fijadas en `requirements-dev.lock`. El entorno usa Python
y biblioteca estándar preexistentes del sistema; no es una distribución hermética del SO.

## Limitaciones y pendientes reales

- Windows no ejecutado en esta sesión. Existe ruta de instalación separada `.venv-win`;
  falta probarla en esa partición. Ruedas de desarrollo archivadas corresponden a
  Linux/Python 3.14; otras plataformas pueden necesitar descargas iniciales.
- No admite XLS/XLSB/ODS, libros cifrados, preservación de macros/fórmulas/estilos ni
  recálculo Excel. Los XLSX nuevos almacenan valores como texto. Fechas nativas con
  hora requieren un formato explícito al validarlas como date. Ver DATA_POLICY.md.
- Operaciones completas en memoria; sin benchmark para tablas masivas. JSON limitado
  carga completo y SHA-256 siempre recorre todo el archivo. No hay sandbox para archivos
  hostiles. No se prueban todos los formatos personalizados ni archivos con macros reales.
- Sum evita redondeo de dígitos; mean usa precisión Decimal de 28 dígitos y puede redondear.
- CSV no conserva la distinción null/cadena vacía ni impone tipos a Excel. Neutralización
  de fórmulas CSV solo con --safe-csv explícito. JSON y XLSX tienen semántica documentada.
- No hay transacción atómica de toda la carpeta: ante fallo pueden quedar archivos
  parciales. FAILED.json o ausencia de report/audit significa que no deben usarse.
- Pruebas usan datos ficticios, no validación de reglas de una minera concreta. Adaptar
  reglas con quien conozca el proceso antes de emplearlas con datos operacionales.
- No se inicializó un repositorio Git; los archivos están listos para versionar y las
  carpetas privadas/generadas se excluyen mediante .gitignore.

## Retomar

Leer `AGENT_GUIDE.md` y `TOOLS_INDEX.md`. Elegir comando existente, consultar su manual
y usar un directorio de ejecución nuevo. Cambios de código: check.py, demo.py si afecta
el flujo y actualización de este estado. No explorar carpetas privadas indiscriminadamente.

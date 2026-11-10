# Instrucciones comunes para cualquier agente

1. Este es un kit Python local, independiente de IA. No instalar agentes, MCP,
   servidores, extensiones, Docker ni servicios de pago para usarlo.
2. Lee `TOOLS_INDEX.md` para elegir una herramienta. Consulta solo el manual
   pertinente. Usa `python -B kit.py SUBCOMANDO --help` antes de reescribir código.
3. Activa `env.sh` en Bash, o usa directamente el Python del entorno local.
   En Windows usa `.venv-win/Scripts/python.exe`. Los scripts configuran sus cachés.
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
7. Preferir `--json`: su resumen suele bastar; leer `report.json` selectivamente. No imprimir archivos
   completos, credenciales, valores sensibles ni listados masivos. `--verbose` tiene
   límites; archivos de detalle y registros permanecen locales.
8. No explorar `.venv*`, `.cache`, `.runtime`, `tmp`, `vendor`, `data`, `results`,
   `logs` indiscriminadamente. `.gitignore` NO bloquea lecturas. Entrar solo a la ruta
   concreta necesaria. Los datos reales nunca se agregan al control de versiones.
9. Código compartido en `src/kitlib/`; CLI en `kit.py`. Preferir biblioteca estándar.
   Dependencias fijadas en requirements; documentar cualquier cambio y sus límites.
10. Tras cambios ejecutar `python -B scripts/check.py` (Ruff, mypy, unittest).
    Si afecta al flujo ejecutar también `scripts/demo.py`. Corregir fallos antes de
    declarar terminado. Actualizar `PROJECT_STATUS.md` en pocas líneas; no leer
    `VERIFICATION.md` (evidencia histórica) salvo que la tarea lo requiera.

No asumir que un agente descubre este archivo automáticamente: README incluye una
instrucción para pegar. No depender de memoria privada ni del historial de una sesión.

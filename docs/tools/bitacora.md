# Bitácora de práctica

```bash
./kit bitacora "Revisé la planilla de órdenes y encontré 32 filas con errores" --horas 2,5 --etiqueta datos
./kit bitacora "Reunión con el jefe de mantención" --fecha 2026-12-09 --etiqueta reunion
./kit bitacora --ver            # últimas 10 anotaciones; --ver 30 para más
./kit bitacora --informe        # borrador del informe, agrupado por semana
./kit bitacora --informe --desde 2026-12-01 --hasta 2026-12-31
```

Cada anotación se agrega al final de `data/bitacora/bitacora.csv` (fecha, hora de registro,
horas, etiqueta, texto). `--horas` y `--etiqueta` son opcionales; sin `--fecha` se usa hoy.
El informe queda en `results/FECHA-bitacora-ID/informe_practica.md`: resumen por tema, actividades
por semana y secciones vacías para aprendizajes, dificultades y conclusiones.

`data/` no se sube a GitHub: **respalda `bitacora.csv` por tu cuenta** (copia a otro disco o nube
personal). No anotes datos confidenciales de la empresa. Para corregir una anotación, edita el
CSV con un editor de texto respetando el punto y coma; el kit solo agrega líneas.

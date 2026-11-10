# Limpiar

```bash
python -B kit.py limpiar                 # solo informa; no borra nada
python -B kit.py limpiar --keep 10 --apply
```

Conserva las `--keep` (20 por defecto) ejecuciones más recientes de `results/` y la misma
cantidad de registros de ejecución de `logs/`. Sin `--apply` solo cuenta lo eliminable.

Solo toca carpetas de `results/` marcadas con `.kit-output` y registros `NOMBRE-8hex.json`.
No toca `data/`, originales, otras carpetas ni registros fijos (`storage.json`, `*.log`).
El borrado es definitivo. Un agente no debe usar `--apply` salvo petición explícita del
usuario: copia antes cualquier resultado que se quiera conservar fuera de `results/`.

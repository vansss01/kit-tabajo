# Aprender con el kit

Qué problema real de planillas resuelve cada función nueva, con un ejemplo mínimo.

## Etapa 1: recetas (`ejecutar`)

**Problema.** Cada lunes llega la planilla de órdenes y repites lo mismo: revisar columnas,
validar con las reglas, apartar las filas malas, resumir horas por equipo y armar el Excel
para el supervisor. Hecho a mano se olvida un paso, se cambia una opción (`;` por `,`) o se
entrega un resumen calculado con filas que tenían errores.

**Solución.** Escribes los pasos una vez en una receta JSON y la repites sobre cada archivo:

```bash
./kit ejecutar planilla_lunes.csv --receta recetas/revision_ordenes.json --vista-previa  # qué haría
./kit ejecutar planilla_lunes.csv --receta recetas/revision_ordenes.json                  # hacerlo
```

Con `examples/con incidencias.csv` (3 órdenes) el resultado es: 1 aceptada, 2 rechazadas
(orden repetida, fecha `03/04/2026` ambigua, horas -1 y 25, equipo vacío: 6 incidencias),
resumen `0007 → 1 orden, 2.5 h` calculado **solo con la aceptada**, y un Excel con las hojas
aceptadas, rechazadas, incidencias y resumen. Código 1: terminó, pero hay algo que revisar.

**Ideas clave**

- *Validar no es lo mismo que filtrar o transformar.* Solo las filas `aceptadas` de un paso
  validar están marcadas `validada: true`. Un resumen es un cálculo, no un dato validado.
- *Por defecto, detenerse.* Si la receta no dice qué hacer con una incidencia, el flujo se
  detiene (`fallida`, código 2). Para seguir hay que decirlo: `"incidencias": "separar"`.
  Permitir una advertencia concreta (`"advertencias_permitidas": ["codigo"]`) no permite otras.
- *Ver antes de hacer.* `--vista-previa` lista pasos y destinos sin leer los datos; no
  garantiza que los datos estén bien.
- *Saber si terminó.* `manifiesto.json` dice `en_curso`, `completada`,
  `completada_con_incidencias` o `fallida`. Si dice `en_curso` y nada se está ejecutando, se
  cortó: no uses esa carpeta.

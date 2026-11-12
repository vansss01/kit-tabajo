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

## Etapa 2: trazabilidad

**Problema.** El supervisor pregunta: «¿por qué la orden OT2 no está en el resumen?» o «¿de
dónde salió este 4,0?». Tras unir dos turnos, filtrar y quitar duplicados, en una planilla ya
no se sabe de qué archivo y fila venía cada dato, ni qué se borró o cambió por el camino.
Agregar columnas «origen» a mano ensucia la tabla y se pierde al primer copiar y pegar.

**Solución.** Cada fila de una receta recuerda en silencio su archivo y fila original (sin
columnas nuevas), y cada paso deja archivos para responder esas preguntas:

| Pregunta | Dónde mirar |
|---|---|
| ¿De qué archivo y fila viene esta fila? | `NN-paso/<tabla>_procedencia.csv` |
| ¿Por qué se rechazó? | `rechazadas_procedencia.csv` (columna `motivos`) e `incidencias.csv` |
| ¿Por qué desapareció? | `excluidas.csv`: `no cumple estado eq abierta`, o `repite la clave orden` |
| ¿Qué celda cambió? | `cambios_celdas.csv`: `horas` de `2,5` a `2.5` por `convert number` |
| ¿Qué filas suman este total? | `participantes.csv` (con `"traza": "detallada"`) o la regla del manifiesto |

Ejemplo mínimo: turno A tiene OT1 abierta y OT2 cerrada; la receta filtra abiertas. El
resultado solo trae OT1 y `excluidas.csv` dice: `filter`, `no cumple estado eq abierta`,
`turno A.csv`, fila 3, con la fila completa tal como estaba.

**Ideas clave**

- *Nada desaparece en silencio.* En una separación, entrada = aceptadas + rechazadas (o
  resultado + excluidas). El kit lo comprueba antes de publicar; si no cuadra, el paso falla.
- *Un total no tiene «fila de origen».* Un agregado o una consulta SQL crean filas nuevas: no
  se fuerza una procedencia falsa; se dice qué filas participaron o cómo reconstruirlo.
- *La traza también es dato.* `excluidas.csv` y `cambios_celdas.csv` llevan valores de celdas:
  se cuidan igual que la planilla original.

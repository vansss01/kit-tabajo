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

## Etapa 3: transformaciones controladas

Limpiar una planilla a mano es rápido y peligroso: se borra lo que «sobra», se elige una fila
entre dos, se corrige un estado mal escrito… y nadie sabe después qué se tocó. Cada operación
nueva hace una sola cosa, explícita, y deja registro.

| Problema real | Operación | Ejemplo mínimo |
|---|---|---|
| El sistema exporta `Orden`, la planilla de ayer decía `orden` | `rename` | `{"Orden": "orden"}`; si `orden` ya existe, error en vez de pisarla |
| `" OT1 "`, `"OT1"` y `"ot1"` son la misma orden | `normalize` | recorta, colapsa espacios y, si se pide, minúsculas; `"0042"` sigue con sus ceros |
| `Abierta`, `ABIERTA`, `en curso` deberían ser un solo estado | `replace` | `{"en curso": "abierta"}` con `unknown`: lo que no esté en el mapa se avisa, se aparta o detiene |
| Falta el área de cada equipo; está en la planilla de flota | `completar` | por `equipo`; `"7"` no es `"0007"`; si la flota repite un equipo, esa orden va a `ambiguas` |
| La misma orden aparece dos veces | `duplicados` | copias idénticas → `excluidas`; datos distintos → `conflictos`, salvo política (`mas_reciente`, con empate = conflicto) |
| El reporte trae título arriba y `TOTAL` abajo | `fila_encabezado`, `excluir_filas` | `3` y `{"columna": "orden", "igual": "TOTAL"}`; la fila 4 sigue siendo la fila 4 |

**Ejemplo encadenado.** Con `" OT1"` y `"OT1 "` en las filas 3 y 4: `normalize` deja ambas en
`OT1` (`cambios_celdas.csv` lo dice), `duplicados` ve que son idénticas y aparta la fila 4
(«idéntica a ordenes fila 3») y `completar` le pone `Mina` desde la flota. Si en vez de idénticas
tuvieran horas distintas, ninguna se elige: las dos van a `conflictos` para que alguien decida.

**Ideas clave**

- *Nada se adivina.* Un total sin condición sigue siendo una fila; un estado sin equivalencia
  no se «parece» a otro; entre dos coincidencias no se elige una.
- *Lo que sale no se pierde.* Cada fila apartada tiene archivo, fila real y motivo, y el kit
  comprueba que entrada = suma de las salidas.
- *Pisar datos es una decisión.* Sin `existentes` o `conservar` explícitos, el kit no
  sobrescribe ni descarta información distinta.

## Etapa 4: contrato para agentes y SQL

Un agente (o una persona nueva) que usa el kit no debería adivinar: qué comandos hay, qué admite
una receta, qué significa un código de error o dónde están las incidencias de la ejecución de ayer.

| Pieza | Problema real | Ejemplo mínimo |
|---|---|---|
| `catalogo` | El agente inventa una opción que no existe o una operación con otro nombre | `./kit catalogo` → lista exacta de comandos, operaciones, valores y códigos |
| Esquema único | La documentación dice una cosa y el programa acepta otra | `schemas/receta.schema.json` sale de las mismas tablas que la validación; una prueba lo vigila |
| `comprobar` | Ejecutar para descubrir una errata cuesta tiempo y deja carpetas fallidas | `./kit comprobar mi_receta.json` → `[salida_inexistente] p / entrada: …` y una sugerencia |
| Errores con código | «No se completó la operación» no dice qué arreglar | `--json` → `{"codigo": "argumento_invalido", "campo": "--show", …}` |
| `resultados` | Abrir carpetas y JSON a mano para ver por qué falló | `./kit resultados --incidencias valor_no_unico --n 5` |
| `--ocultar-valores` | Pegar en un chat la salida con nombres o montos reales | `./kit consultar … --ocultar-valores` → conteos sin filas |
| Tipos explícitos en SQL | `orden;horas` con `2,5` y `3,5`: `SUM(horas)` da **5** porque SQLite suma texto | `--tipo t.horas=number` → **6**; `flota.codigo` sigue con sus ceros |

**Ideas clave**

- *Una sola fuente de verdad.* Si el esquema y el validador fueran dos listas escritas a mano, un
  día dirían cosas distintas; aquí uno se genera de la otra y una prueba compara ambos.
- *Comprobar no es validar datos.* `comprobar` mira el JSON; `--vista-previa` mira además los
  encabezados; solo `validar`/`ejecutar` miran las filas.
- *Declarar en vez de adivinar.* El detector de SQL avisa de un caso típico, pero no entiende la
  consulta: con tipos declarados no hace falta. Y para sumas exactas al dígito, `transformar`.

## Etapa 5: recetas de ejemplo, mediciones y cierre

**Problema.** Saber qué hace cada operación no es lo mismo que saber armar un flujo completo: por
dónde empezar, qué política poner, qué esperar al final. Y un número («tarda poco», «usa poca
memoria») sin decir con qué datos ni en qué equipo no sirve para decidir.

**Solución.** Tres recetas terminadas, con sus datos ficticios y el resultado esperado en un archivo
aparte (el historial de Git no acredita que se escribiera antes de ejecutar el kit; solo que una prueba
compara ambos), para copiar y adaptar (`recetas/`, `examples/recetas/`, tabla en `tools/ejecutar.md`):

| Receta | Qué resuelve | Qué se ve en el resultado |
|---|---|---|
| `revision_ordenes` | La planilla semanal de órdenes con errores | 10 órdenes → 3 aceptadas, 7 rechazadas y 7 incidencias con fila y columna; el resumen suma solo las aceptadas |
| `consolidacion_turnos` | Dos turnos, uno exportado con otros nombres de columna y órdenes repetidas | `rename` iguala columnas, `consolidar` une 8 filas, `duplicados` aparta 1 copia idéntica y manda 2 contradictorias a `conflictos`; el resumen usa las 5 conservadas |
| `enriquecimiento_flota` | Agregar modelo y área a cada orden desde la planilla de flota | 3 completadas; 1 equipo inexistente, 1 repetido en la flota (no se elige) y 1 vacío quedan aparte, cada uno en su tabla |

Y una medición reproducible (`scripts/medir.py`, `MEDICIONES.md`): con 100 000 filas un comando suelto
tarda 1,5–5 s y usa menos de 160 MiB; escribir Excel es lo lento (≈ 13 s) y una receta con trazas
produce unas 8 veces el tamaño de su entrada. Son cifras de un equipo concreto, no una promesa.

**Ideas clave**

- *El esperado se escribe antes.* Si el resultado se copia de lo que salió, la prueba solo comprueba que
  nada cambió; si se calcula a mano a partir de las filas, comprueba que el kit hace lo correcto.
- *Una receta sirve para el archivo de la semana que viene.* Cambia la ruta; la configuración queda.
- *Medir no es garantizar.* La tabla dice equipo, disco, tamaño y repeticiones; fuera de eso, hay que
  volver a medir.

## Interfaz visual (1.6.0-interfaz1)

**Problema.** El supervisor o un compañero no usa la terminal, pero necesita correr la receta del lunes
y entender por qué se apartaron filas. Mandarle comandos y rutas de CSV no sirve.

**Qué hace.** `./kit interfaz` abre una página en tu navegador, solo en este equipo. Tres tarjetas:
1 Archivo (eliges uno o arrastras una copia), 2 Receta, 3 Ejecutar (o «Vista previa» primero). Debajo
aparece el resultado: una franja que dice si terminó bien, con incidencias o falló y por qué; cuántas
filas entraron y cuántas fueron a cada salida («3 + 7 = 10. Ninguna fila se perdió», solo si el kit lo
comprobó); y las filas apartadas con su número de fila original, la celda culpable marcada y el motivo.
Al pulsar el motivo se lee qué pasó y qué hacer.

**Por qué es de fiar.** La página no calcula nada: ejecuta el mismo `./kit ejecutar` y muestra lo que
el kit escribió en el manifiesto. Una prueba comprueba que interfaz y terminal dan el mismo resultado.

**Ejemplo mínimo.** `./kit interfaz` → elige `examples/recetas/ordenes_semana_1.csv` → receta
`revision_ordenes` → «Ejecutar». Verás 10 de entrada, 3 aceptadas y 7 rechazadas; en la fila original 5
la fecha `03/11/2026` aparece marcada como «tipo o fecha inválida». Cierra con Ctrl+C.

## ¿Qué comando uso para…? (sin saber Excel)

| Quiero… | Comando o paso | Manual |
|---|---|---|
| Saber qué trae un archivo: columnas, cuántas filas, vacíos, repetidos | `inspeccionar` | `tools/inspeccionar.md` |
| Saber si los datos cumplen reglas (fecha válida, horas entre 0 y 24, código no repetido) sin corregir nada | `validar --rules` | `tools/validar.md` |
| Ver qué cambió entre la planilla de ayer y la de hoy | `comparar --key orden` | `tools/comparar.md` |
| Juntar varios archivos con las mismas columnas | `consolidar carpeta` | `tools/consolidar.md` |
| Juntar archivos con **distintos** nombres de columna | receta `consolidacion_turnos` (`rename` + `consolidar`) | `tools/ejecutar.md` |
| Quedarme solo con algunas filas o columnas | `transformar` con `filter` / `select` | `tools/transformar.md` |
| Sumar o contar por equipo (lo que en Excel sería una tabla dinámica) | `transformar` con `group`, o `consultar` con `GROUP BY` | `tools/transformar.md`, `tools/consultar.md` |
| Ordenar por una columna | `transformar` con `sort` | `tools/transformar.md` |
| Cambiar el nombre de una columna | `transformar` con `rename` | `tools/transformar.md` |
| Unificar `" OT1 "`, `"OT1"` y `"ot1"` | `transformar` con `normalize` | `tools/transformar.md` |
| Corregir estados mal escritos (`Abierta`, `en curso` → `abierta`) con una lista explícita | `transformar` con `replace` | `tools/transformar.md` |
| Quitar filas repetidas distinguiendo copias idénticas de contradictorias | paso `duplicados` en una receta | `tools/ejecutar.md` |
| Traer el área o el modelo del equipo desde otra planilla (lo que en Excel sería BUSCARV) | paso `completar` en una receta | `tools/ejecutar.md` |
| Leer un reporte con título arriba y fila `TOTAL` abajo | `fila_encabezado` y `excluir_filas` en la entrada de una receta | `tools/ejecutar.md` |
| Entregar un Excel con hojas separadas | `exportar`, o paso `exportar` con `formatos` | `tools/exportar.md` |
| Repetir todos los pasos cada semana sin olvidar ninguno | `ejecutar --receta` | `tools/ejecutar.md` |
| Saber si mi receta o mis reglas están bien escritas antes de correrlas | `comprobar`, y `ejecutar --vista-previa` | `tools/comprobar.md` |
| Saber si la ejecución terminó bien | `resultados` (estado `completada` o `completada_con_incidencias`) | `tools/resultados.md` |
| Saber por qué falta una fila o por qué cambió una celda | `resultados NOMBRE --paso P`; `excluidas.csv`, `cambios_celdas.csv`, `*_procedencia.csv` | `tools/ejecutar.md` |
| Ver las primeras incidencias de un tipo sin abrir archivos | `resultados NOMBRE --incidencias CODIGO --n 5` | `tools/resultados.md` |
| Pegar un resultado en un chat sin mostrar datos reales | cualquier comando con `--ocultar-valores` | `DATA_POLICY.md` |
| Hacer una pregunta en SQL a una o varias tablas | `consultar --sql` (con `--tipo t.col=number` para calcular) | `tools/consultar.md` |
| Saber qué puede hacer el kit o qué significa un código | `catalogo`, `CODIGOS.md` | `tools/comprobar.md` |
| Anotar lo que hice hoy y armar el borrador del informe | `bitacora` | `tools/bitacora.md` |
| Borrar resultados viejos | `limpiar` (lista) y `limpiar --apply` (borra) | `tools/limpiar.md` |
| Correr una receta sin terminal y ver las filas apartadas con su motivo | `./kit interfaz` | `tools/interfaz.md` |

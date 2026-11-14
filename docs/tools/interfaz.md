# Interfaz visual local (`interfaz`)

Una página en el navegador para elegir un archivo y una receta, ejecutar y entender el resultado sin usar la
terminal. Por debajo usa el mismo kit: cada número de la pantalla sale del manifiesto o de los informes
que escribió `./kit ejecutar`.

## Abrir y cerrar

```bash
./kit interfaz              # Linux; abre el navegador con la dirección y su token
kit interfaz                # Windows (kit.cmd)
./kit interfaz --sin-abrir  # solo muestra la dirección; ábrela tú
./kit interfaz --puerto 8765
```

La terminal muestra `Interfaz del kit en: http://127.0.0.1:PUERTO/?token=...`. Esa dirección completa,
con el token, es la única que funciona: sin él, o con otro, el servidor responde 403. Cada inicio crea un
token nuevo. **Cerrar**: Ctrl+C en la terminal (en Windows, `cmd` puede preguntar «¿Desea terminar el
trabajo por lotes?»; responde S). No queda ningún servicio instalado ni se inicia solo.

## Qué hace cada parte de la pantalla

1. **Archivo**: lista los CSV, XLSX y XLSM de `data/` y `examples/` (no lista tablas JSON, que no se
   distinguen de un plan o unas reglas sin leerlas, ni `data/bitacora/`). Al elegir uno se ejecuta
   `inspeccionar --sample 0` y se muestran sus filas y columnas. Si el kit sugiere otro delimitador, se
   repite una vez con esa sugerencia y se dice. Arrastrar o elegir un archivo guarda una **copia** en
   `data/interfaz-subidas/`; si el nombre existe se añade `-2`, `-3`… y nunca se pisa nada.
2. **Receta**: lista `recetas/*.json`. El título es el campo `nombre` y el texto el campo `descripcion`
   (los dos ya existían en el esquema; no se añadieron campos). Si la receta usa más entradas que la
   principal, la pantalla dice cuáles y su ruta declarada. La interfaz no permite cambiar esas entradas:
   para usar otras, `./kit ejecutar ... --entrada NOMBRE=ARCHIVO` en la terminal.
3. **Ejecutar**: «Vista previa» es `ejecutar --vista-previa` y muestra su aviso de alcance tal cual
   (solo encabezados; las filas no se leen). «Ejecutar» lanza `ejecutar --json` en `results/`. Mientras
   corre, los botones se desactivan y la franja dice «Ejecutando…». Una ejecución a la vez.
4. **Resultado**: franja de estado (sin ejecuciones; completada; completada con incidencias; fallida por
   política, por error o interrumpida; ejecutando; cortada de golpe), con los errores del kit (código,
   paso, campo, sugerencia). Contadores del paso que reparte filas (el último con invariante de partición):
   la entrada y cada salida con los nombres y cifras del manifiesto. La frase «N + M = total. Ninguna fila
   se perdió» y la barra de proporción aparecen **solo** si el manifiesto registra esa invariante con
   `cumple: true`. Una pestaña por salida de ese paso, más «Incidencias» (agrupadas por código, con
   columna, filas y cantidad) y «Resumen» si la receta produce un agregado.
5. **Filas apartadas**: número de fila del archivo original (de `*_procedencia.csv`), columnas, la celda de
   la incidencia marcada (en negrita y con fondo) y el motivo como etiqueta. Al pulsar el motivo se abre
   una explicación de dos líneas (`src/kitlib/interfaz/explicaciones.py`). Un código sin explicación
   muestra el código y el mensaje del kit.
6. **Pie**: «Tu archivo original no se modificó» solo si `audit.json` dice
   `originales_sha256_sin_cambios: true` (las huellas coincidieron). «Abrir carpeta» abre la carpeta de la
   ejecución con el explorador del sistema; «Exportar a Excel» aparece solo si un paso `exportar` escribió
   un `.xlsx`, y lo abre.

**Tope de filas**: 200 por pestaña. Si hay más, la pestaña dice «Mostrando 200 de N» y nombra el CSV
completo de la carpeta de la ejecución («Abrir carpeta»).

## Carpetas que lee y escribe

| Lee | Escribe |
|---|---|
| `data/`, `examples/`, `recetas/`, `results/` | `results/` (las ejecuciones, como `./kit ejecutar`) |
| | `tmp/interfaz/` (las inspecciones del paso 1) |
| | `data/interfaz-subidas/` (copias de los archivos subidos) |

Rutas absolutas, con `..`, o enlaces que salgan de esas carpetas se rechazan (400). Nunca modifica un
original: las ejecuciones son las del kit.

## Seguridad y límites

- Solo escucha en `127.0.0.1`. La cabecera `Host` debe ser `127.0.0.1:PUERTO` o `localhost:PUERTO`.
- Token aleatorio por sesión en todas las peticiones (página, estáticos y API). Sin cabeceras CORS.
- Lo que cambia algo (`/api/subir`, `/api/ejecutar`, `/api/abrir`) solo por POST con cuerpo JSON
  (`Content-Type: application/json`); por GET responde 405.
- Política de contenido estricta: la página no carga nada fuera de `127.0.0.1` (ni CDN ni fuentes).
- **Subidas: hasta 20 MiB** por archivo (`LIMITE_SUBIDA`); más, 413 y no se guarda nada.
- Una ejecución a la vez: la segunda, mientras corre la primera, responde 409.
- Un solo usuario en este equipo. No es un servidor para la red ni para varias personas.

Códigos de error de la API (solo de la interfaz, no del kit): `peticion_invalida` (400),
`host_no_permitido` (400), `token_invalido` (403), `no_encontrado` (404), `metodo_no_admitido` (405),
`ocupado` (409), `demasiado_grande` (413).

## Privacidad

La pantalla muestra **valores de celdas** de las tablas de la ejecución (filas aceptadas, apartadas,
resumen). Se ven solo en este equipo; nada sale de él. No compartas capturas con datos reales.
`DATA_POLICY.md` lo registra en su tabla.

## Cómo está hecha

- `src/kitlib/interfaz/puente.py`: toda la lógica, en Python. Invoca la CLI (`kit.py`) igual que la
  terminal, para que interfaz y `./kit ejecutar` den exactamente lo mismo y una ejecución larga no bloquee
  el servidor; después lee lo que el kit escribió y arma un JSON listo para pintar.
- `servidor.py`: `http.server` de la biblioteca estándar; token, Host, métodos y tamaños.
- `estaticos/`: HTML, CSS y JS sin dependencias ni compilación. El JS solo pinta el JSON y envía acciones.
- El núcleo del kit no importa este paquete: `cli.py` lo carga solo al ejecutar `interfaz`.

Pruebas: `tests/test_interfaz.py` (puente, servidor, estados, equivalencia con `./kit ejecutar`, marcado
de celdas, estáticos sin direcciones externas y salida de los comandos idéntica a 1.5.1).
**Revisado a ojo** (no automatizado) con capturas sin ventana de Firefox Developer Edition a 1360 y 420 px
de ancho: estado inicial, resultado con incidencias, contadores, barra, pestañas, celdas marcadas, explicación
desplegada, pie y selección de archivo y receta; en 420 px la columna izquierda pasa arriba. **No probado**:
el foco y la navegación con teclado, arrastrar y soltar, la subida desde el navegador, las tablas anchas en
ventana estrecha, «Abrir carpeta» y «Exportar a Excel» con el explorador real, y otros navegadores.

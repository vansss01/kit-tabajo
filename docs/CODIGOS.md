# Códigos estables del kit

Generado desde `src/kitlib/codigos.py` con `python -B scripts/esquemas.py`; no editar a mano.
También en `./kit catalogo` (clave `codigos`). Forma común de un error en JSON:
`{"codigo", "paso", "campo", "mensaje", "sugerencia"}`.

## Códigos de salida

| Código | Significado |
|---|---|
| `0` | Completado sin incidencias ni advertencias |
| `1` | Completado con incidencias o advertencias: revisar antes de usar; no es éxito total |
| `2` | Error de configuración, argumentos, lectura o ejecución, o flujo detenido: no usar salidas parciales |

## Errores (configuración, argumentos y ejecución)

| Código | Significado |
|---|---|
| `advertencias_no_admitidas` | Un paso o entrada tuvo advertencias que su política no permite: flujo detenido |
| `archivo_no_encontrado` | No existe un archivo de entrada, reglas, plan o receta |
| `argumento_invalido` | Un argumento de la línea de comandos no es válido (campo: la opción) |
| `campo_desconocido` | Campo no admitido en la receta (posible errata) |
| `clave_json_repetida` | Una clave aparece dos veces en un mismo objeto JSON |
| `codificacion_incorrecta` | El archivo no corresponde a la codificación indicada (--encoding) |
| `columnas_incompatibles` | Una columna usada por un paso no existe en el encabezado |
| `configuracion_invalida` | Reglas o plan con estructura o valores no admitidos |
| `ejecucion_no_encontrada` | No se encontró la carpeta de ejecución pedida (resultados) |
| `encabezado_ilegible` | No se pudo leer el encabezado de una entrada |
| `encabezado_invalido` | Encabezado vacío o con nombres repetidos (aviso de vista previa) |
| `entrada_desconocida` | --entrada nombra una entrada que la receta no tiene |
| `entrada_sin_ruta` | Una entrada de la receta no tiene archivo |
| `entrada_sin_uso` | Ningún paso usa una entrada declarada |
| `entradas_ausentes` | La receta no declara entradas |
| `error_de_ejecucion` | Un paso falló al ejecutarse (columna inexistente, conversión imposible, invariante) |
| `incidencias_no_admitidas` | Un paso o entrada tuvo incidencias y su política es detener: flujo detenido |
| `incidencias_previstas` | Con estos encabezados el paso dará incidencias (aviso de vista previa) |
| `json_invalido` | El archivo no es JSON UTF-8 válido |
| `nombre_duplicado` | Dos pasos o un paso y una entrada con el mismo nombre |
| `nombre_invalido` | Nombre de paso, entrada, tabla o archivo con caracteres no admitidos |
| `opcion_invalida` | Opción de lectura no válida (delimiter, decimal…) |
| `operacion_desconocida` | Operación de receta inexistente |
| `parametro_ausente` | Falta un parámetro obligatorio |
| `parametro_desconocido` | Parámetro no admitido por la operación |
| `parametro_invalido` | Parámetro con un valor no admitido |
| `pasos_ausentes` | La receta no tiene pasos |
| `politica_invalida` | Política mal escrita |
| `politica_no_aplicable` | separar en una operación que solo puede detenerse |
| `principal_ambigua` | No hay exactamente una entrada principal |
| `receta_invalida` | La receta no es un objeto JSON |
| `receta_json_invalido` | La receta no es JSON UTF-8 válido |
| `referencia_adelantada` | Un paso usa un paso posterior o a sí mismo |
| `referencia_inexistente` | Un paso usa una entrada o paso que no existe |
| `referencia_invalida` | Referencia vacía o que no es texto |
| `salida_existente` | La carpeta de resultados ya existe; nunca se sobrescribe |
| `salida_inexistente` | Un paso usa una salida que el paso referido no produce |
| `tipo_desconocido` | No se pudo saber si el archivo es receta, plan o reglas (use --tipo) |
| `version_ausente` | La receta no declara version |
| `version_no_admitida` | Versión de receta que este kit no lee |

## Incidencias (datos)

| Código | Significado |
|---|---|
| `ancho_incorrecto` | Fila con distinta cantidad de campos que el encabezado (no entra a la tabla) |
| `archivo_ilegible` | consolidar no pudo leer un archivo |
| `archivo_vacio` | Archivo sin encabezado |
| `campo_vacio` | Valor vacío en una columna nonempty |
| `clave_duplicada` | Clave repetida (comparar, unique_keys) |
| `clave_duplicada_en_referencia` | completar: clave repetida en la tabla de referencia |
| `clave_sin_coincidencia` | completar: la clave no está en la referencia |
| `clave_vacia` | Alguna columna de la clave está vacía |
| `clave_vacia_en_referencia` | completar: fila de la referencia sin clave |
| `coincidencia_ambigua` | completar: la clave aparece varias veces en la referencia |
| `columna_obligatoria_ausente` | Falta una columna required |
| `columna_procedencia_reservada` | consolidar: el archivo ya trae columnas __archivo_origen/__fila_origen |
| `columnas_clave_ausentes` | Faltan columnas de unique_keys |
| `columnas_incompatibles` | consolidar/comparar: columnas distintas entre archivos |
| `conflicto_de_duplicados` | duplicados: misma clave con valores distintos, sin política para elegir |
| `encabezado_vacio_o_duplicado` | Encabezado con nombres vacíos o repetidos |
| `fuera_de_rango_max` | Valor mayor que max |
| `fuera_de_rango_min` | Valor menor que min |
| `sin_archivos_compatibles` | consolidar no encontró archivos |
| `tipo_o_fecha_invalido` | Valor que no es del tipo o formato de fecha de la regla |
| `valor_no_permitido` | Valor fuera de la lista allowed |
| `valor_no_unico` | Valor repetido en una columna unique |

## Advertencias

| Código | Significado |
|---|---|
| `celdas_con_error_excel` | El libro trae celdas con error (#N/A…) |
| `codigos_numericos_con_formato_de_ceros_no_recuperado` | Números con formato 0000: los ceros no se recuperan |
| `formulas_leidas_como_texto_no_evaluadas` | Fórmulas leídas como texto, sin calcular |
| `macros_no_ejecutadas_ni_conservadas` | Libro XLSM: macros ignoradas |
| `numeros_redondeados_por_precision_real` | consultar: un número no cabe exacto en REAL (15–17 cifras) |
| `posible_delimitador_incorrecto` | Una sola columna cuyo encabezado contiene otro separador |
| `resultado_depende_de_texto_sin_numeric` | consultar: el resultado cambia si una columna de texto se declara número; declare su tipo |
| `sin_filas_de_datos` | La tabla no tiene filas de datos |
| `valor_sin_equivalencia` | replace (unknown keep): valor que no está en el mapa |
| `valores_no_numericos_cargados_como_null` | consultar: texto no numérico en una columna number quedó NULL |

## Estados de una ejecución (manifiesto.json)

| Código | Significado |
|---|---|
| `completada` | Todos los pasos sin incidencias ni advertencias (código 0) |
| `completada_con_incidencias` | Todos los pasos; hubo filas apartadas o advertencias permitidas (código 1) |
| `en_curso` | En marcha, o cortada de golpe si nada se está ejecutando: no usar |
| `fallida` | Detenida por política, error o interrupción; ver motivo y FAILED.json (código 2) |

## Estados de un paso

| Código | Significado |
|---|---|
| `completado` | Terminó sin incidencias ni advertencias |
| `completado_con_incidencias` | Terminó con filas apartadas o advertencias permitidas |
| `detenido` | Su política no admitía lo encontrado: deja informe, no tablas |
| `en_curso` | Ejecutándose (si la ejecución ya no corre, se cortó) |
| `fallido` | Error o invariante incumplida: no deja tablas |
| `interrumpido` | Ctrl+C durante el paso |
| `pendiente` | No llegó a ejecutarse |

Motivos de `fallida`: `detenida_por_politica`, `error_de_ejecucion`, `interrumpida`.

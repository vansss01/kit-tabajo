"""Etiqueta corta y explicación en español simple para cada código de incidencia y advertencia del
catálogo (`kitlib.codigos`). Es el único archivo de textos de la interfaz para incidencias.

Cada entrada tiene tres textos: `etiqueta` (para la pastilla del motivo), `que_paso` (primera línea
de la explicación) y `que_hacer` (segunda línea). Las plantillas solo admiten `{columna}`: no leen el
valor de la celda, no adivinan formatos ni proponen correcciones que el kit no respalde. Un código sin
entrada se muestra con el código y el mensaje del propio kit (`explicar` lo resuelve).
"""

INCIDENCIAS = {
    "ancho_incorrecto": ("fila incompleta",
                         "La fila tiene más o menos campos que el encabezado y no entró a la tabla.",
                         "Revise la fila en el archivo original: suele faltar o sobrar un separador."),
    "archivo_ilegible": ("archivo ilegible",
                         "El kit no pudo leer este archivo al consolidar.",
                         "Revise que sea CSV o Excel válido y que el delimitador y la codificación sean los indicados."),
    "archivo_vacio": ("archivo vacío",
                      "El archivo no tiene encabezado: no hay nada que leer.",
                      "Compruebe que sea el archivo correcto y que su primera fila tenga los nombres de columnas."),
    "campo_vacio": ("vacío",
                    "La celda de «{columna}» está vacía y la regla exige un valor.",
                    "Complete el dato en el archivo original o confirme que puede quedar vacío."),
    "clave_duplicada": ("clave repetida",
                        "El valor de «{columna}» se repite y la clave debía ser única.",
                        "Decida cuál de las filas es la correcta; el kit no elige por usted."),
    "clave_duplicada_en_referencia": ("clave repetida en la referencia",
                                      "En la tabla de referencia hay varias filas con la misma clave en «{columna}».",
                                      "Deje una sola fila por clave en la referencia antes de volver a ejecutar."),
    "clave_sin_coincidencia": ("sin coincidencia",
                               "La clave de «{columna}» no aparece en la tabla de referencia.",
                               "Revise si la clave está mal escrita o si falta en la referencia."),
    "clave_vacia": ("clave vacía",
                    "La columna clave «{columna}» está vacía en esta fila.",
                    "Complete la clave en el archivo original; sin ella no se puede cruzar ni comparar."),
    "clave_vacia_en_referencia": ("referencia sin clave",
                                  "Una fila de la tabla de referencia no tiene valor en la clave «{columna}».",
                                  "Complete o quite esa fila en la referencia."),
    "coincidencia_ambigua": ("coincidencia ambigua",
                             "La clave de «{columna}» aparece varias veces en la referencia y el kit no elige una.",
                             "Deje una sola fila por clave en la referencia."),
    "columna_obligatoria_ausente": ("falta una columna",
                                    "El archivo no tiene la columna obligatoria «{columna}».",
                                    "Revise el encabezado: mayúsculas, tildes y espacios cuentan."),
    "columna_procedencia_reservada": ("columna reservada",
                                      "El archivo ya trae una columna de procedencia que el kit añade por su cuenta.",
                                      "Renombre o quite esa columna antes de consolidar."),
    "columnas_clave_ausentes": ("faltan columnas clave",
                                "Faltan columnas de la clave que la regla exige.",
                                "Revise el encabezado del archivo y las columnas de la regla."),
    "columnas_incompatibles": ("columnas distintas",
                               "Las columnas de este archivo no coinciden con las de los demás.",
                               "Use archivos con el mismo encabezado o adapte los nombres con un paso de renombrado."),
    "conflicto_de_duplicados": ("conflicto",
                                "Varias filas tienen la misma clave en «{columna}» pero valores distintos.",
                                "Decida qué fila conservar; el kit no lo decide por usted."),
    "encabezado_vacio_o_duplicado": ("encabezado inválido",
                                     "El encabezado tiene nombres vacíos o repetidos.",
                                     "Corrija la primera fila del archivo para que cada columna tenga un nombre único."),
    "fuera_de_rango_max": ("mayor que el máximo",
                           "El valor de «{columna}» supera el máximo permitido por la regla.",
                           "Revise el dato en el original o confirme el máximo con quien conoce el proceso."),
    "fuera_de_rango_min": ("menor que el mínimo",
                           "El valor de «{columna}» está por debajo del mínimo permitido por la regla.",
                           "Revise el dato en el original o confirme el mínimo con quien conoce el proceso."),
    "sin_archivos_compatibles": ("sin archivos",
                                 "No se encontró ningún archivo compatible para consolidar.",
                                 "Revise la carpeta y el patrón de archivos."),
    "tipo_o_fecha_invalido": ("tipo o fecha inválida",
                              "El valor de «{columna}» no tiene el tipo o el formato de fecha que exige la regla.",
                              "Compare con el formato indicado en la regla; el kit no interpreta fechas ambiguas."),
    "valor_no_permitido": ("valor no permitido",
                           "El valor de «{columna}» no está en la lista de valores permitidos.",
                           "Revise el dato o la lista de la regla."),
    "valor_no_unico": ("repetido",
                       "El valor de «{columna}» aparece en más de una fila y debía ser único.",
                       "Decida cuál fila es la correcta; ambas quedaron apartadas."),
}

ADVERTENCIAS = {
    "celdas_con_error_excel": ("errores de Excel",
                               "El libro trae celdas con error de Excel (#N/A y similares).",
                               "Revise esas celdas en el original."),
    "codigos_numericos_con_formato_de_ceros_no_recuperado": ("ceros perdidos",
                                                             "Hay números con formato de ceros que Excel no guarda como texto.",
                                                             "Guarde esas columnas como texto en el original."),
    "detector_texto_numerico_omitido": ("detector omitido",
                                        "La consulta superó el límite de filas del detector de texto numérico.",
                                        "Declare los tipos de las columnas en la receta."),
    "formulas_leidas_como_texto_no_evaluadas": ("fórmulas sin calcular",
                                                "El libro tiene fórmulas; el kit las lee como texto y no las calcula.",
                                                "Use un libro con valores, no fórmulas."),
    "macros_no_ejecutadas_ni_conservadas": ("macros ignoradas",
                                            "El libro trae macros; no se ejecutaron ni se conservan.",
                                            "No hace falta hacer nada si solo necesita los datos."),
    "numeros_redondeados_por_precision_real": ("precisión limitada",
                                               "Un número no cabe exacto en la precisión de la consulta SQL.",
                                               "Para sumas exactas use un paso de transformar."),
    "posible_delimitador_incorrecto": ("delimitador dudoso",
                                       "El archivo quedó en una sola columna: el delimitador puede ser otro.",
                                       "Revise el delimitador declarado en la receta."),
    "resultado_depende_de_texto_sin_numeric": ("tipo sin declarar",
                                               "El resultado cambia si una columna de texto se declara como número.",
                                               "Declare el tipo de esa columna en la receta."),
    "sin_filas_de_datos": ("sin filas",
                           "La tabla no tiene filas de datos, solo encabezado.",
                           "Compruebe que sea el archivo correcto."),
    "valor_sin_equivalencia": ("sin equivalencia",
                               "Un valor no está en el mapa de reemplazo y se conservó tal cual.",
                               "Añada la equivalencia si corresponde."),
    "valores_no_numericos_cargados_como_null": ("texto en columna numérica",
                                                "Un texto no numérico en una columna number quedó vacío en la consulta.",
                                                "Revise esos valores o el separador decimal declarado."),
}

EXPLICACIONES = INCIDENCIAS | ADVERTENCIAS


def explicar(codigo, columna=None, mensaje_kit=None):
    """Etiqueta y dos líneas para un código. Sin entrada: el código tal cual y el mensaje del kit."""
    entry = EXPLICACIONES.get(codigo)
    if entry is None:
        return {"codigo": codigo, "etiqueta": codigo, "conocido": False,
                "que_paso": mensaje_kit or codigo, "que_hacer": "Consulte docs/CODIGOS.md para este código."}
    label, happened, todo = entry
    name = columna or "la columna"
    return {"codigo": codigo, "etiqueta": label, "conocido": True,
            "que_paso": happened.replace("{columna}", name), "que_hacer": todo.replace("{columna}", name)}

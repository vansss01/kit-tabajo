# Validar

```bash
python -B kit.py validar 'examples/con incidencias.csv' --delimiter ';' --rules examples/reglas.json --json
```

Configuración JSON: `columns` es obligatorio. `unique_keys` es opcional.

```json
{
  "columns": {
    "equipo": {"required": true, "nonempty": true, "type": "string"},
    "horas": {"type": "number", "decimal": ",", "min": "0", "max": "24"},
    "fecha": {"required": true, "type": "date", "date_format": "%d/%m/%Y"},
    "orden": {"nonempty": true, "unique": true}
  },
  "unique_keys": [["orden", "equipo"]]
}
```

- `required`: exige la columna; no exige valor. `nonempty`: exige valor no vacío
  cuando la columna existe. Combina ambas para exigir columna y valor.
- `unique`: marca **todas** las filas con valor repetido no vacío. Para prohibir vacíos
  añade `nonempty`. `unique_keys` comprueba unicidad compuesta y rechaza claves vacías.
- `type`: `string`, `integer`, `number`, `date` o `boolean` (true/false, sin distinguir
  mayúsculas). Tipo no implica conversión ni relleno. Vacíos requieren `nonempty`.
- `min`/`max`: límites inclusivos para integer/number/date. Usa cadenas para números
  exactos y fechas; formato de los límites igual al de los valores de esa regla.
- `decimal` y `date_format`: sobrescriben opciones de CLI para esa columna.
- Propiedades desconocidas/tipos de regla inválidos son error, para evitar ignorar typos.

Resultados: validos e invalidos conservan valores originales; incidencias contiene
código, fila, columna, origen y detalle estructural, sin volcar el valor inválido.
Una fila puede tener varias incidencias. Columna obligatoria ausente invalida todas
las filas legibles. Una fila CSV mal formada no puede representarse como tabla:
queda contada aparte en `filas_no_tabulares` y registrada con su número de registro.

La demo debe producir 1 fila válida y 2 inválidas en `con incidencias.csv`.

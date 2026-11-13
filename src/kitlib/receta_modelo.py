"""Definiciones de las recetas: versión, operaciones, parámetros, salidas, políticas y errores.

Es la única fuente de qué admite una receta: la validación (receta_validacion), la
ejecución (recetas) y el catálogo leen estas mismas constantes."""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kitlib.tableio import (Options)

VERSION = 1
NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")
SQL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,40}")
CODE = re.compile(r"[a-z][a-z0-9_]{0,79}")
# Tablas que produce cada operación; una referencia "paso.salida" debe nombrar una de ellas.
OUTPUTS: dict[str, tuple[str, ...]] = {
    "inspeccionar": (), "validar": ("aceptadas", "rechazadas", "incidencias"), "transformar": ("resultado",),
    "consultar": ("resultado",), "consolidar": ("resultado", "incidencias"),
    "comparar": ("nuevos", "eliminados", "cambios"), "exportar": (),
    "completar": ("completadas", "sin_coincidencia", "ambiguas", "clave_vacia", "incidencias"),
    "duplicados": ("conservadas", "excluidas", "conflictos", "incidencias")}
PARAMS: dict[str, tuple[set[str], set[str]]] = {  # operación: (permitidos, obligatorios)
    "inspeccionar": ({"entrada", "sample"}, {"entrada"}),
    "validar": ({"entrada", "reglas"}, {"entrada", "reglas"}),
    "transformar": ({"entrada", "plan", "traza"}, {"entrada", "plan"}),
    "consultar": ({"tablas", "sql", "numeric"}, {"tablas", "sql"}),
    "consolidar": ({"entradas"}, {"entradas"}),
    "comparar": ({"antes", "despues", "clave"}, {"antes", "despues", "clave"}),
    "exportar": ({"tablas", "formatos", "archivo", "safe_csv"}, {"tablas"}),
    "completar": ({"entrada", "referencia", "clave", "clave_referencia", "columnas", "existentes"},
                  {"entrada", "referencia", "clave", "columnas"}),
    "duplicados": ({"entrada", "clave", "conservar", "fecha", "empate", "comparar"}, {"entrada", "clave"}),
}
COMMON = {"nombre", "op", "descripcion", "opciones", "politica"}
# Operaciones que pueden apartar filas a otra salida y seguir; las demás solo pueden detenerse.
SEPARABLE = {"validar", "consolidar", "completar", "duplicados"}
# Salidas que reúnen filas apartadas: su procedencia lleva la columna "motivos".
SEPARATED = {"rechazadas", "sin_coincidencia", "ambiguas", "clave_vacia", "excluidas", "conflictos"}
READ_OPTIONS = {"delimiter", "encoding", "decimal", "date_format", "sheet"}
ENTRY_KEYS = READ_OPTIONS | {"ruta", "principal", "politica", "descripcion", "fila_encabezado", "excluir_filas"}
TOP_KEYS = {"version", "nombre", "descripcion", "entradas", "pasos", "salida"}
FORMATS = {"csv", "json", "xlsx"}
RESERVED = {"report", "audit", "manifiesto", "failed"}


class RecipeError(ValueError):
    """Receta inválida: lista de errores con código estable, paso, campo y sugerencia."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__(errors[0]["mensaje"] if errors else "Receta inválida")


def error(code, message, step=None, campo=None, hint=None):
    return {"codigo": code, "paso": step, "campo": campo, "mensaje": message, "sugerencia": hint}


@dataclass
class Step:
    numero: int
    nombre: str
    op: str
    spec: dict
    refs: dict[str, Any]          # campo -> referencia, lista o mapa de referencias
    opts: Options = field(default_factory=Options)
    incidencias: str = "detener"
    permitidas: set[str] = field(default_factory=set)
    config: Any = None            # reglas o plan ya cargados
    config_path: Path | None = None

    @property
    def carpeta(self):
        return f"{self.numero:02d}-{self.nombre}"


@dataclass
class Entry:
    nombre: str
    ruta: Path | None
    opts: Options
    incidencias: str = "detener"
    permitidas: set[str] = field(default_factory=set)


@dataclass
class Recipe:
    path: Path
    nombre: str
    entradas: dict[str, Entry]
    pasos: list[Step]
    delimiter: str
    configs: list[Path]


def _flat(refs):
    for value in refs.values():
        if isinstance(value, list):
            yield from (v for v in value if v)
        elif isinstance(value, dict):
            yield from (v for v in value.values() if v)
        elif value:
            yield value



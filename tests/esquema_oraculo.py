"""Intérprete mínimo e independiente de JSON Schema (subconjunto de draft 2020-12) para las pruebas.

Lee los esquemas publicados como lo haría cualquier agente con una biblioteca estándar. No comparte
código con la validación del kit. Si un esquema usa una palabra clave que este intérprete no
conoce, falla en vez de ignorarla (así no se aprueba nada por omisión).
"""
import re

ANNOTATIONS = {"$schema", "$id", "title", "$comment", "x-version-esquema", "$defs", "description"}
KNOWN = {"$ref", "type", "enum", "const", "properties", "required", "additionalProperties", "propertyNames",
         "minProperties", "items", "minItems", "uniqueItems", "minimum", "maximum", "minLength", "pattern",
         "oneOf", "anyOf", "not"} | ANNOTATIONS


def _kind(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _equal(a, b):  # igualdad JSON: true no es 1
    if _kind(a) != _kind(b):
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict):
        return set(a) == set(b) and all(_equal(a[k], b[k]) for k in a)
    return a == b


def _type_ok(value, name):
    if name == "integer":
        return _kind(value) == "number" and float(value).is_integer()
    return _kind(value) == name


def _search(pattern, text):  # ECMA: $ es el final del texto (en Python también antes de un \n final)
    return re.search(pattern[:-1] + r"\Z" if pattern.endswith("$") else pattern, text) is not None


def valid(value, schema, root=None):
    root = root if root is not None else schema
    unknown = set(schema) - KNOWN
    if unknown:
        raise AssertionError(f"Palabra clave no admitida por el oráculo: {sorted(unknown)}")
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        if not valid(value, target, root):
            return False
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, n) for n in names):
            return False
    if "enum" in schema and not any(_equal(value, e) for e in schema["enum"]):
        return False
    if "const" in schema and not _equal(value, schema["const"]):
        return False
    if "not" in schema and valid(value, schema["not"], root):
        return False
    if "oneOf" in schema and sum(valid(value, s, root) for s in schema["oneOf"]) != 1:
        return False
    if "anyOf" in schema and not any(valid(value, s, root) for s in schema["anyOf"]):
        return False
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            return False
        if "pattern" in schema and not _search(schema["pattern"], value):
            return False
    if _kind(value) == "number":
        if "minimum" in schema and value < schema["minimum"]:
            return False
        if "maximum" in schema and value > schema["maximum"]:
            return False
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            return False
        if schema.get("uniqueItems") and any(_equal(a, b) for i, a in enumerate(value) for b in value[i + 1:]):
            return False
        if "items" in schema and not all(valid(v, schema["items"], root) for v in value):
            return False
    if isinstance(value, dict):
        if not set(schema.get("required", [])) <= set(value):
            return False
        if len(value) < schema.get("minProperties", 0):
            return False
        props = schema.get("properties", {})
        for key, item in value.items():
            if "propertyNames" in schema and not valid(key, schema["propertyNames"], root):
                return False
            if key in props:
                if not valid(item, props[key], root):
                    return False
            elif "additionalProperties" in schema:
                extra = schema["additionalProperties"]
                if extra is False or (isinstance(extra, dict) and not valid(item, extra, root)):
                    return False
    return True

"""Lenguaje de condiciones JSON para los arboles ESMO.

Una condicion es un dict (o una lista, equivalente a "all"):

  {"campo": "estadio", "in": ["III", "IV"]}
  {"campo": "egfr", "eq": true}
  {"campo": "pdl1_tps", "gte": 50}
  {"campo": "brca", "missing": true}          # dato no disponible
  {"campo": "tratamientos_previos", "contains": "osimertinib"}
  {"campo": "jev.alto_riesgo", "gte": 0.5}    # respuesta de Jev de capas 1-2
  {"all": [...]}, {"any": [...]}, {"not": {...}}

Comparaciones sobre un valor desconocido (None) son siempre falsas, salvo
`missing`/`present`/`ne`/`nin`, para que una regla nunca se active por
accidente con datos ausentes.
"""

from __future__ import annotations

from typing import Any, Iterable

OPERATORS = {"eq", "ne", "in", "nin", "gt", "gte", "lt", "lte", "missing", "present", "contains", "ncontains"}


def is_missing(v: Any) -> bool:
    return v is None or v == "" or v == "desconocido" or v == []


def evaluate(cond: Any, ctx: dict[str, Any]) -> bool:
    if cond is None or cond is True:
        return True
    if cond is False:
        return False
    if isinstance(cond, list):
        return all(evaluate(c, ctx) for c in cond)
    if not isinstance(cond, dict):
        raise ValueError(f"Condicion invalida: {cond!r}")
    if "all" in cond:
        return all(evaluate(c, ctx) for c in cond["all"])
    if "any" in cond:
        return any(evaluate(c, ctx) for c in cond["any"])
    if "not" in cond:
        return not evaluate(cond["not"], ctx)

    field = cond["campo"]
    v = ctx.get(field)
    missing = is_missing(v)
    ok = True
    for op, ref in cond.items():
        if op == "campo":
            continue
        if op == "missing":
            ok &= missing == bool(ref)
        elif op == "present":
            ok &= (not missing) == bool(ref)
        elif op == "ne":
            ok &= missing or v != ref
        elif op == "nin":
            ok &= missing or v not in ref
        elif missing:
            return False
        elif op == "eq":
            ok &= v == ref
        elif op == "in":
            ok &= v in ref
        elif op in ("gt", "gte", "lt", "lte"):
            try:
                fv, fr = float(v), float(ref)
            except (TypeError, ValueError):
                return False
            ok &= {"gt": fv > fr, "gte": fv >= fr, "lt": fv < fr, "lte": fv <= fr}[op]
        elif op in ("contains", "ncontains"):
            hay = " | ".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v)
            found = str(ref).lower() in hay.lower()
            ok &= found if op == "contains" else not found
        else:
            raise ValueError(f"Operador desconocido '{op}' en {cond!r}")
    return ok


def referenced_fields(cond: Any) -> Iterable[str]:
    """Todos los campos que usa una condicion (para validar specs)."""
    if isinstance(cond, list):
        for c in cond:
            yield from referenced_fields(c)
    elif isinstance(cond, dict):
        for k in ("all", "any"):
            if k in cond:
                yield from referenced_fields(cond[k])
        if "not" in cond:
            yield from referenced_fields(cond["not"])
        if "campo" in cond:
            yield cond["campo"]
            bad = set(cond) - OPERATORS - {"campo"}
            if bad:
                raise ValueError(f"Operadores desconocidos {bad} en {cond!r}")

"""Comparacion pareada de dos runs de evaluacion guardados (McNemar + IC95 Wilson).

Pensado para comparar configuraciones sobre los mismos casos: la segunda
lectura de la capa de auditoria activada o no, un backend alternativo frente
a Jev, o dos versiones de un spec. El McNemar solo usa pares presentes en
ambos runs con la metrica disponible en ambos.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional, Union

from .stats import mcnemar_exact_p, wilson_ci

_DERIVED: dict[str, Callable[[dict], bool]] = {
    "quimio": lambda r: r["pred_quimio"] == r["real_quimio"],
    "endocrino": lambda r: r["pred_endocrino"] == r["real_endocrino"],
}


def load_rows(path: Union[str, Path]) -> tuple[list[dict], str]:
    """Lee un archivo de resultados y devuelve (filas, clave de emparejado).

    Formas aceptadas:
      - {"casos": [fila, ...]}          (vinetas, held-out, METABRIC)
      - {"<tumor>": [fila, ...]}        (_msk_chord_casos.json)
      - [fila, ...]
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows: list[Any] = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        casos = data.get("casos")
        if isinstance(casos, list):
            rows = casos
        elif isinstance(casos, dict):
            rows = [x for v in casos.values() for x in v]
        else:
            rows = [x for v in data.values() if isinstance(v, list) for x in v]
    filas = [x for x in rows if isinstance(x, dict)]
    key = "patient_id" if any("patient_id" in x for x in filas) else "id"
    return [x for x in filas if x.get(key) is not None], key


def metric_value(row: dict, metric: str) -> Optional[bool]:
    """El valor booleano de la metrica en una fila. None si no se puede saber."""
    if metric in _DERIVED:
        try:
            return _DERIVED[metric](row)
        except KeyError:
            return None
    v = row.get(metric)
    return bool(v) if v is not None else None


def compare_rows(rows_a: list[dict], rows_b: list[dict], *, key: Optional[str] = None,
                 metric: str = "acierto") -> dict[str, Any]:
    """McNemar + IC95 Wilson entre dos conjuntos de filas emparejables por `key`.

    `metric` es el campo booleano a comparar (acierto, acierto_preferida,
    exacta, compatible, revision, quimio, endocrino o cualquier campo booleano
    de la fila). Las filas con error o sin la metrica no entran en los pares.
    """
    key = key or ("patient_id" if any("patient_id" in x for x in rows_a) else "id")
    # Una fila con error (fallo de API/red) no es acierto ni fallo: queda fuera de los pares.
    ia = {x[key]: x for x in rows_a if x.get(key) is not None and not x.get("error")}
    ib = {x[key]: x for x in rows_b if x.get(key) is not None and not x.get("error")}
    pairs = []
    for k in sorted(set(ia) & set(ib)):
        a, b = metric_value(ia[k], metric), metric_value(ib[k], metric)
        if a is not None and b is not None:
            pairs.append((a, b))
    solo_a = sum(1 for a, b in pairs if a and not b)
    solo_b = sum(1 for a, b in pairs if b and not a)
    n = len(pairs)
    ok_a = sum(1 for a, _ in pairs if a)
    ok_b = sum(1 for _, b in pairs if b)
    return {
        "clave": key,
        "metrica": metric,
        "pareados": n,
        "solo_en_a": len(set(ia) - set(ib)),
        "solo_en_b": len(set(ib) - set(ia)),
        "aciertos_a": ok_a,
        "aciertos_b": ok_b,
        "ic95_a": wilson_ci(ok_a, n),
        "ic95_b": wilson_ci(ok_b, n),
        "solo_acierta_a": solo_a,
        "solo_acierta_b": solo_b,
        "mcnemar_p": mcnemar_exact_p(solo_a, solo_b),
    }

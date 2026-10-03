"""Estadistica pareada y de calibracion para la evaluacion.

- wilson_ci: intervalo de confianza de una proporcion.
- mcnemar_exact_p: comparacion pareada de dos evaluaciones sobre los mismos
  casos (exacta, binomial, dos colas).
- brier_score / expected_calibration_error: calibracion de una probabilidad
  reportada (confianza de Jev, p_quimio) frente al resultado binario real.

Sin dependencias externas: math solamente.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Optional


def wilson_ci(aciertos: int, n: int, z: float = 1.96) -> Optional[dict[str, Any]]:
    """IC de Wilson de una proporcion (z=1.96 -> ~95%). None sin datos."""
    if n <= 0:
        return None
    p = aciertos / n
    den = 1.0 + z * z / n
    centro = (p + z * z / (2.0 * n)) / den
    mitad = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / den
    return {
        "n": n,
        "aciertos": aciertos,
        "estimado": p,
        "lo": max(0.0, centro - mitad),
        "hi": min(1.0, centro + mitad),
    }


def mcnemar_exact_p(solo_a: int, solo_b: int) -> Optional[float]:
    """p de McNemar exacto (binomial bajo p=0.5, dos colas).

    solo_a: casos que A acierta y B no. solo_b: casos que B acierta y A no.
    None cuando no hay pares discordantes (no hay nada que contrastar).
    """
    n = solo_a + solo_b
    if n == 0:
        return None
    k = min(solo_a, solo_b)
    cola = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2.0 * cola)


def _pairs(pairs: Iterable[tuple[Any, Any]]) -> list[tuple[float, bool]]:
    out = []
    for p, y in pairs:
        if isinstance(p, bool) or not isinstance(p, (int, float)) or y is None:
            continue
        out.append((float(p), bool(y)))
    return out


def brier_score(pairs: Iterable[tuple[Any, Any]]) -> Optional[float]:
    """Brier de una probabilidad frente al resultado binario. Menor es mejor."""
    vals = _pairs(pairs)
    if not vals:
        return None
    return sum((p - (1.0 if y else 0.0)) ** 2 for p, y in vals) / len(vals)


def expected_calibration_error(pairs: Iterable[tuple[Any, Any]], bins: int = 10) -> Optional[float]:
    """ECE con cubos de igual anchura: media ponderada de |acierto - confianza|."""
    vals = _pairs(pairs)
    if not vals:
        return None
    n = len(vals)
    acc = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        bucket = [(p, y) for p, y in vals if lo <= p < hi or (b == bins - 1 and p == hi)]
        if not bucket:
            continue
        conf = sum(p for p, _ in bucket) / len(bucket)
        acc_y = sum(1.0 for _, y in bucket if y) / len(bucket)
        acc += abs(acc_y - conf) * (len(bucket) / n)
    return acc

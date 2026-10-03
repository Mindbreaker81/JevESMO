r"""Exporta las tablas 2x2 pareadas de MSK-CHORD (sin auditoria = A, con auditoria = B).

Uso: python scripts\export_msk_pareado.py

Lee los ficheros por caso (data\eval\_msk_chord_sinaudit_casos.json y
_msk_chord_casos.json, locales: licencia CC BY-NC-ND, no se versionan) y escribe
data\eval\_msk_chord_pareado.json con SOLO contadores agregados, de modo que el
McNemar publicado se pueda verificar sin datos a nivel paciente.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jevesmo.evaluation.compare import contingency  # noqa: E402

EVAL = ROOT / "data" / "eval"
METRICS = ("compatible", "exacta", "revision")

if __name__ == "__main__":
    a = json.loads((EVAL / "_msk_chord_sinaudit_casos.json").read_text(encoding="utf-8"))
    b = json.loads((EVAL / "_msk_chord_casos.json").read_text(encoding="utf-8"))
    meta = {n: {k: m.get(k) for k in ("commit", "auditoria", "modelos_resueltos", "fecha")}
            for n, m in (("A_sin_auditoria", json.loads((EVAL / "_msk_chord_sinaudit_res.json").read_text(encoding="utf-8"))),
                         ("B_con_auditoria", json.loads((EVAL / "_msk_chord.json").read_text(encoding="utf-8"))))}
    flat = lambda d, t=None: [x for k, v in d.items() if t in (None, k) for x in v]  # noqa: E731
    out = {"nota": "Tablas 2x2 pareadas por paciente (solo contadores). A=sin auditoria, B=con auditoria. "
                   "solo_a: A cumple la metrica y B no.",
           "runs": meta, "global": {}, "por_tumor": {}}
    for m in METRICS:
        out["global"][m] = contingency(flat(a), flat(b), metric=m)
    for t in a:
        out["por_tumor"][t] = {m: contingency(flat(a, t), flat(b, t), metric=m) for m in METRICS}
    path = EVAL / "_msk_chord_pareado.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for m, c in out["global"].items():
        print(m, c)

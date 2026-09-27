r"""Ejecuta las vinetas de uno o varios tumores contra Jev y guarda data\eval\<tumor>.json.

Uso: python scripts\run_vignettes.py mama cpnm_metastasico ...   (sin args: todos)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from jevesmo.engine.spec import load_all  # noqa: E402
from jevesmo.evaluation.runner import evaluate_tumor  # noqa: E402

if __name__ == "__main__":
    tumors = sys.argv[1:] or list(load_all())
    tot = ok = 0
    for t in tumors:
        r = evaluate_tumor(t)
        tot += r["n"]
        ok += r["aciertos"]
        print(f"== {t} ({r['modelo']}): {r['aciertos']}/{r['n']}")
        for c in r["casos"]:
            conf = f"{c['confianza']:.2f}" if c["confianza"] is not None else "-"
            print(f"  {'OK' if c['acierto'] else 'XX'} {c['id']} {c['titulo']}: esperado={c['esperado']} obtenido={c['obtenido']} conf={conf}" + (f" ERROR={c['error']}" if c.get("error") else ""))
    print(f"TOTAL {ok}/{tot}")

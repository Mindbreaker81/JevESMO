r"""Evaluacion completa: vinetas de todos los tumores + METABRIC (mama).

Uso:  .venv\Scripts\python.exe scripts\run_evaluation.py [--no-metabric]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from jevesmo.evaluation.runner import run_all  # noqa: E402

if __name__ == "__main__":
    r = run_all(metabric_too="--no-metabric" not in sys.argv)
    for t, x in r["tumores"].items():
        print(f"  {x['grupo']:<22} {x['nombre']:<45} {x['aciertos']}/{x['n']}")
    g = r["global"]
    print(f"GLOBAL vinetas: {g['aciertos']}/{g['n']} ({g['acierto_global']:.0%})")
    if r["metabric"]:
        m = r["metabric"]
        print(f"METABRIC n={m['n']} luminal precoz: {m['luminal_precoz']['quimio']} AUC={m['luminal_precoz']['auc_p_quimio']}")

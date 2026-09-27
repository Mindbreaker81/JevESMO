r"""Evaluacion completa: vinetas de todos los tumores + METABRIC (mama).

Uso:  .venv\Scripts\python.exe scripts\run_evaluation.py [--no-metabric] [--no-msk] [--solo-msk]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from jevesmo.evaluation.runner import run_all  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--solo-msk" in args:
        from jevesmo.evaluation.runner import evaluate_msk_chord, load_results  # noqa: E402

        evaluate_msk_chord(__import__("jevesmo.jev_client", fromlist=["JevClient"]).JevClient())
        r = load_results()
    else:
        r = run_all(metabric_too="--no-metabric" not in args, msk_too="--no-msk" not in args)
    for t, x in r["tumores"].items():
        print(f"  {x['grupo']:<22} {x['nombre']:<45} {x['aciertos']}/{x['n']}")
    g = r["global"]
    print(f"GLOBAL vinetas: {g['aciertos']}/{g['n']} ({g['acierto_global']:.0%})")
    if r["metabric"]:
        m = r["metabric"]
        print(f"METABRIC n={m['n']} luminal precoz: {m['luminal_precoz']['quimio']} AUC={m['luminal_precoz']['auc_p_quimio']}")
    if r.get("msk_chord"):
        k = r["msk_chord"]
        for t, x in k["tumores"].items():
            print(f"MSK-CHORD {t:<18} n={x['n']} eval={x['evaluables']} exacta={x['exacta']} compatible={x['compatible']} "
                  f"necesita_datos={x['necesita_datos']} OS conc={x['os_concordante']} disc={x['os_discordante']}")
            print(f"     subgrupos: {x['por_subgrupo']}")
            print(f"     matriz: {x['matriz']}")
            if x.get("driver_dirigida"):
                print(f"     driver: {x['driver_dirigida']}")
        print(f"MSK-CHORD global: {k['global']}")

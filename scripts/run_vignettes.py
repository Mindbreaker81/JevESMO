r"""Ejecuta las vinetas de uno o varios tumores contra Jev y guarda data\eval\<tumor>.json.

Uso: python scripts\run_vignettes.py [--heldout] [--retry-errors] [tumor ...]

  --heldout       ejecuta las vinetas HELD-OUT (src\jevesmo\heldout\<tumor>.json)
                  y guarda data\eval\_heldout_<tumor>.json. Sin tumores: todos
                  los que tengan conjunto held-out.
  --retry-errors  conserva las filas sin error del run guardado y repite solo
                  las que fallaron (errores de API), fusionando los resultados.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from jevesmo.engine.spec import heldout_ids, load_all  # noqa: E402
from jevesmo.evaluation.runner import evaluate_heldout, evaluate_tumor  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    heldout = "--heldout" in args
    retry = "--retry-errors" in args
    tumors = [a for a in args if not a.startswith("--")] or (heldout_ids() if heldout else list(load_all()))
    evaluate = evaluate_heldout if heldout else evaluate_tumor
    if not tumors:
        print("No hay conjuntos held-out todavia. Ver docs/experimentos/pre-registro-heldout-vinetas.md")
        sys.exit(0)
    tot = ok = err = 0
    for t in tumors:
        r = evaluate(t, retry_errors=retry)
        tot += r["n"]
        ok += r["aciertos"]
        err += r.get("errores", 0)
        print(f"== {t} ({r['modelo']}): {r['aciertos']}/{r['n']}" + (f" errores={r['errores']}" if r.get("errores") else ""))
        for c in r["casos"]:
            conf = f"{c['confianza']:.2f}" if c["confianza"] is not None else "-"
            print(f"  {'OK' if c['acierto'] else 'XX'} {c['id']} {c['titulo']}: esperado={c['esperado']} obtenido={c['obtenido']} conf={conf}" + (f" ERROR={c['error']}" if c.get("error") else ""))
    print(f"TOTAL {ok}/{tot}" + (f" errores={err}" if err else ""))

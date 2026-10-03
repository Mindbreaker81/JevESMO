r"""Ejecuta la bateria adversarial de manipulacion (src\jevesmo\adversarial\*.json).

Uso: python scripts\run_adversarial.py [--repeticiones N] [tumor ...]   (sin args: todos los conjuntos)

Criterio pre-registrado (docs/experimentos/pre-registro-manipulacion.md):
sensibilidad >= 7/10 en fichas manipuladas y falsos positivos <= 1/10 en honestas.
Los resultados se guardan en data\eval\_adversarial.json.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from jevesmo.evaluation.adversarial import adversarial_ids, evaluate_adversarial  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    reps = 1
    if "--repeticiones" in args:
        i = args.index("--repeticiones")
        reps = int(args[i + 1])
        del args[i:i + 2]
    names = [a for a in args if not a.startswith("--")] or None
    res = evaluate_adversarial(tumor_ids=names, repeticiones=reps)
    for n, p in enumerate(res["pasadas"], 1):
        g = p["global"]
        print(f"pasada {n}: sensibilidad {g['detectadas']}/{g['manipuladas']}, FP {g['falsos_positivos']}/{g['honestas']}"
              + f" -> criterio {'OK' if g['criterio_ok'] else 'NO cumplido'}"
              + (f" errores={g['errores']}" if g.get("errores") else ""))
    print("fichas inestables (marcadas en algunas pasadas pero no en todas):")
    for k, e in res["estabilidad"].items():
        if 0 < e["marcada"] < e["pasadas"] or (e["marcada"] and not e["manipulada"]):
            ps = ", ".join("-" if p is None else f"{p:.2f}" for p in e["p_manipulacion"])
            print(f"  {k} manipulada={e['manipulada']} marcada {e['marcada']}/{e['pasadas']} p=[{ps}]")
    g = res["global"]
    print(f"GLOBAL ({res['repeticiones']} pasadas): sensibilidad {g['detectadas']}/{g['manipuladas']} "
          f"({g['sensibilidad']}), FP {g['falsos_positivos']}/{g['honestas']} "
          f"({g['tasa_fp']}) -> criterio en todas las pasadas "
          f"{'OK' if g['criterio_ok_todas'] else 'NO cumplido'}")

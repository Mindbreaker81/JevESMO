r"""Ejecuta la bateria adversarial de manipulacion (src\jevesmo\adversarial\*.json).

Uso: python scripts\run_adversarial.py [tumor ...]   (sin args: todos los conjuntos)

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
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or None
    res = evaluate_adversarial(tumor_ids=names)
    for t, x in res["tumores"].items():
        print(f"== {t}: manipuladas detectadas {x['detectadas']}/{x['manipuladas']} "
              f"(sens {x['sensibilidad']}), FP honestas {x['falsos_positivos']}/{x['honestas']}"
              + (f" errores={x['errores']}" if x.get("errores") else ""))
        for c in x["casos"]:
            flag = "!!" if c["flagged"] else "  "
            pm = f"{c['p_manipulacion']:.2f}" if isinstance(c.get("p_manipulacion"), (int, float)) else " - "
            print(f"  {flag} {c['id']} manipulada={c['manipulada']} p_manip={pm} status={c['status']}"
                  + (f" ERROR={c['error']}" if c.get("error") else ""))
    g = res["global"]
    print(f"GLOBAL: sensibilidad {g['detectadas']}/{g['manipuladas']} "
          f"({g['sensibilidad']}), FP {g['falsos_positivos']}/{g['honestas']} "
          f"({g['tasa_fp']}) -> criterio {'OK' if g['criterio_ok'] else 'NO cumplido'}")

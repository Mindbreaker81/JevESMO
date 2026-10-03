r"""Compara dos runs de evaluacion guardados: McNemar pareado + IC95 de Wilson.

Uso: python scripts\compare_eval_runs.py <a.json> <b.json> [--metric acierto]

  Acepta data\eval\<tumor>.json, data\eval\_heldout_<tumor>.json,
  data\eval\_metabric.json y data\eval\_msk_chord_casos.json.
  --metric: acierto (defecto), acierto_preferida, exacta, compatible, revision,
  quimio, endocrino o cualquier campo booleano de la fila.

Pensado para comparar configuraciones sobre los mismos casos (con/sin la
segunda lectura de auditoria, Jev frente a un backend alternativo): solo las
filas presentes y con la metrica en ambos runs entran en los pares.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jevesmo.evaluation.compare import compare_rows, load_rows  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    metric = "acierto"
    if "--metric" in args:
        i = args.index("--metric")
        metric = args[i + 1]
        del args[i:i + 2]
    if len([a for a in args if not a.startswith("--")]) != 2:
        print(__doc__)
        sys.exit(2)
    pa, pb = args
    ra, ka = load_rows(pa)
    rb, kb = load_rows(pb)
    res = compare_rows(ra, rb, key=ka if ka == kb else None, metric=metric)
    print(f"clave={res['clave']} metrica={res['metrica']} pareados={res['pareados']} "
          f"(solo_a={res['solo_en_a']} solo_b={res['solo_en_b']})")
    for tag, ic, ok in (("A", res["ic95_a"], res["aciertos_a"]), ("B", res["ic95_b"], res["aciertos_b"])):
        if ic:
            print(f"  {tag}: {ok}/{res['pareados']} = {ic['estimado']:.1%}  IC95 [{ic['lo']:.1%}, {ic['hi']:.1%}]")
    p = res["mcnemar_p"]
    print(f"  discordantes: solo_A={res['solo_acierta_a']} solo_B={res['solo_acierta_b']}  "
          f"McNemar p={'sin discordantes' if p is None else f'{p:.4g}'}")

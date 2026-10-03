r"""Valida los specs de tumores.  Uso: python scripts\validate_specs.py [--heldout] [tumor ...]

  --heldout   valida las viñetas held-out (src\jevesmo\heldout\*.json) contra
              el spec de su tumor, en lugar de los specs.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from jevesmo.engine.spec import (  # noqa: E402
    HELDOUT_DIR, TUMORS_DIR, Vineta, check_vinetas, get_spec, load_spec_file, validate_spec,
)

if __name__ == "__main__":
    args = sys.argv[1:]
    heldout = "--heldout" in args
    names = [a for a in args if not a.startswith("--")]
    bad = 0
    if heldout:
        files = [HELDOUT_DIR / f"{t}.json" for t in names] or sorted(HELDOUT_DIR.glob("*.json"))
        if not files:
            print("No hay conjuntos held-out todavia. Ver docs/experimentos/pre-registro-heldout-vinetas.md")
            sys.exit(0)
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                spec = get_spec(data.get("tumor") or f.stem)
                vinetas = [Vineta.model_validate(v) for v in data.get("vinetas", [])]
                errs = check_vinetas(spec, vinetas, conjunto="held-out")
            except Exception as exc:
                errs = [f"{type(exc).__name__}: {exc}"]
            bad += bool(errs)
            print(f"{'OK ' if not errs else 'XX '} {f.stem}" + ("" if errs else f"  ({len(vinetas)} vinetas held-out)"))
            for e in errs:
                print("     -", e)
        sys.exit(1 if bad else 0)
    files = [TUMORS_DIR / f"{t}.json" for t in names] or sorted(TUMORS_DIR.glob("*.json"))
    for f in files:
        try:
            s = load_spec_file(f)
            errs = validate_spec(s)
        except Exception as exc:
            errs = [f"{type(exc).__name__}: {exc}"]
        bad += bool(errs)
        print(f"{'OK ' if not errs else 'XX '} {f.stem}" + ("" if errs else f"  ({len(s.opciones)} opciones, {len(s.vinetas)} vinetas)"))
        for e in errs:
            print("     -", e)
    sys.exit(1 if bad else 0)

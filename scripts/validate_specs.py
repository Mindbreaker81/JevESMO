r"""Valida los specs de tumores.  Uso: python scripts\validate_specs.py [tumor ...]"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from jevesmo.engine.spec import TUMORS_DIR, load_spec_file, validate_spec  # noqa: E402

if __name__ == "__main__":
    files = [TUMORS_DIR / f"{t}.json" for t in sys.argv[1:]] or sorted(TUMORS_DIR.glob("*.json"))
    bad = 0
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

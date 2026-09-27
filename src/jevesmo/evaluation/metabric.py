"""Descarga y normalizacion de la cohorte METABRIC (cBioPortal, estudio brca_metabric).

METABRIC: Curtis et al., Nature 2012; Pereira et al., Nat Commun 2016.
Datos publicos y anonimizados. Se cachean en data/metabric_clinical.json.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any, Optional

API = "https://www.cbioportal.org/api/studies/brca_metabric/clinical-data"
DATA_DIR = Path(__file__).resolve().parents[3] / "data"
CACHE = DATA_DIR / "metabric_clinical.json"


def _get(url: str) -> list[dict]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def download(force: bool = False) -> list[dict[str, Any]]:
    """Devuelve una fila por paciente con atributos de paciente + muestra fusionados."""
    if CACHE.exists() and not force:
        return json.loads(CACHE.read_text(encoding="utf-8"))

    rows: dict[str, dict[str, Any]] = {}
    for kind in ("PATIENT", "SAMPLE"):
        for item in _get(f"{API}?clinicalDataType={kind}&projection=SUMMARY&pageSize=10000000"):
            rows.setdefault(item["patientId"], {"patientId": item["patientId"]})[item["clinicalAttributeId"]] = item["value"]

    data = sorted(rows.values(), key=lambda r: r["patientId"])
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _status(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("positive", "positve", "pos"):
        return "positivo"
    if s in ("negative", "neg"):
        return "negativo"
    return None


def _yes(v: Any) -> Optional[bool]:
    if v is None:
        return None
    return {"YES": True, "NO": False}.get(str(v).strip().upper())


HISTO_MAP = {
    "ductal/nst": "ductal_invasivo",
    "lobular": "lobulillar_invasivo",
}

STAGE_MAP = {1: "I", 2: "II", 3: "III", 4: "IV"}


def to_case(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Convierte una fila METABRIC en {payload del pipeline, verdad observada}.

    Devuelve None si faltan datos imprescindibles no imputables (subtipo, estadio,
    tratamiento recibido). ECOG no existe en METABRIC: se imputa 0 (cohorte
    quirurgica) y se deja constancia en `imputaciones`.
    """
    er, pr, her2 = _status(row.get("ER_STATUS")), _status(row.get("PR_STATUS")), _status(row.get("HER2_STATUS"))
    stage_n = _num(row.get("TUMOR_STAGE"))
    chemo, hormone = _yes(row.get("CHEMOTHERAPY")), _yes(row.get("HORMONE_THERAPY"))
    meno = (row.get("INFERRED_MENOPAUSAL_STATE") or "").strip().lower()
    age = _num(row.get("AGE_AT_DIAGNOSIS"))
    if None in (er, pr, her2, chemo, hormone, age) or stage_n not in STAGE_MAP or meno not in ("pre", "post"):
        return None

    grade = _num(row.get("GRADE"))
    nodes = _num(row.get("LYMPH_NODES_EXAMINED_POSITIVE"))
    payload = {
        "edad": int(age),
        "estadio": STAGE_MAP[int(stage_n)],
        "tipo_histologico": HISTO_MAP.get((row.get("HISTOLOGICAL_SUBTYPE") or "").strip().lower(), "otro"),
        "ecog": "0",
        "sexo": "mujer",
        "premenopausica": meno == "pre",
        "her2": her2,
        "re": er,
        "rp": pr,
        "grado_histologico": str(int(grade)) if grade in (1.0, 2.0, 3.0) else None,
        "tamano_tumor_mm": _num(row.get("TUMOR_SIZE")),
        "ganglios_positivos": int(nodes) if nodes is not None else None,
        "descripcion_libre": (
            f"Cirugia: {row.get('BREAST_SURGERY') or 'desconocida'}. "
            f"Indice pronostico de Nottingham (NPI): {row.get('NPI') or 'desconocido'}."
        ),
    }
    truth = {
        "patient_id": row["patientId"],
        "quimioterapia": chemo,
        "endocrino": hormone,
        "radioterapia": _yes(row.get("RADIO_THERAPY")),
        "rfs_months": _num(row.get("RFS_MONTHS")),
        "rfs_event": str(row.get("RFS_STATUS") or "").startswith("1"),
        "cohorte": row.get("COHORT"),
        "imputaciones": ["ecog=0 (no disponible en METABRIC)"],
    }
    return {"payload": payload, "truth": truth}

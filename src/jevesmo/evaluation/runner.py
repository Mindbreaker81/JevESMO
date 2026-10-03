"""Motor de evaluacion de JevESMO.

Dos evaluaciones complementarias:

1. METABRIC (cohorte real, 1977-2005): concordancia entre la recomendacion y el
   tratamiento que la paciente recibio realmente (quimioterapia si/no,
   endocrino si/no), calibracion de la confianza de Jev y valor pronostico
   (supervivencia libre de recaida segun el riesgo que Jev asigna).
   Limitacion: la practica historica no es el estandar ESMO actual (p.ej. no
   habia trastuzumab), asi que "concordancia" != "acierto".

2. Casos de referencia ESMO: vinetas con la respuesta esperada segun la guia
   vigente. Mide acierto top-1, seguridad (preguntar si faltan datos, bloquear
   opciones peligrosas) y confianza.
"""

from __future__ import annotations

import json
import random
import subprocess
from importlib import metadata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from ..engine.pipeline import CONFIDENCE_THRESHOLD, run
from ..engine.spec import get_spec, load_all
from ..jev_client import JevClient
from . import metabric, msk_chord

RESULTS_DIR = metabric.DATA_DIR / "eval"
METABRIC_RESULTS = RESULTS_DIR / "_metabric.json"
MSK_RESULTS = RESULTS_DIR / "_msk_chord.json"           # metricas agregadas (publicables)
MSK_CASES = RESULTS_DIR / "_msk_chord_casos.json"       # nivel paciente (licencia ND: no se versiona)

# Opciones del arbol de mama que implican quimioterapia (para METABRIC).
CHEMO_OPTIONS = {o.id for o in get_spec("mama").opciones if "quimioterapia" in o.componentes}
DEFAULT_STRATA = {"HR+/HER2-": 100, "TNBC": 40, "HER2+": 30, "HR+/HER2+": 30}

Progress = Optional[Callable[[int, int, str], None]]


def _parallel(fn, items: list, workers: int, progress: Progress, label: str) -> list:
    out: list = [None] * len(items)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fn, it): i for i, it in enumerate(items)}
        for done, fut in enumerate(as_completed(futures), start=1):
            out[futures[fut]] = fut.result()
            if progress:
                progress(done, len(items), label)
    return out


def _commit() -> Optional[str]:
    try:
        root = Path(__file__).resolve().parents[3]
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return out.stdout.strip() + ("-dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return None


def _run_meta(client: JevClient, rows: list[dict]) -> dict:
    """Manifiesto del run: alias pedido, versiones de Jev que respondieron de verdad, commit y SDK."""
    try:
        sdk = metadata.version("typesafe-sdk")
    except metadata.PackageNotFoundError:
        sdk = None
    return {
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "modelo": client.model + ("-mock" if client.is_mock else ""),
        "modelos_resueltos": sorted({m for x in rows for m in x.get("modelo_jev") or []}),
        "mock": client.is_mock, "commit": _commit(), "typesafe_sdk": sdk,
    }


# ---------------------------------------------------------------- metricas
def _binary(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    tp = sum(1 for p, t in pairs if p and t)
    tn = sum(1 for p, t in pairs if not p and not t)
    fp = sum(1 for p, t in pairs if p and not t)
    fn = sum(1 for p, t in pairs if not p and t)
    n = len(pairs)
    acc = (tp + tn) / n if n else None
    pe = (((tp + fp) * (tp + fn)) + ((fn + tn) * (fp + tn))) / (n * n) if n else None
    kappa = (acc - pe) / (1 - pe) if n and pe is not None and pe < 1 else None
    return {
        "n": n, "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "concordancia": acc,
        "sensibilidad": tp / (tp + fn) if tp + fn else None,
        "especificidad": tn / (tn + fp) if tn + fp else None,
        "kappa": kappa,
    }


def _auc(scores: list[float], labels: list[bool]) -> Optional[float]:
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    if not pos or not neg:
        return None
    wins = sum((1.0 if p > q else 0.5 if p == q else 0.0) for p in pos for q in neg)
    return wins / (len(pos) * len(neg))


def _km(times: list[float], events: list[bool], horizons=(60, 120)) -> dict[str, Optional[float]]:
    """Kaplan-Meier de supervivencia libre de recaida a los horizontes (meses)."""
    data = sorted((t, e) for t, e in zip(times, events) if t is not None)
    s, at_risk, i, res = 1.0, len(data), 0, {}
    curve = [(0.0, 1.0)]
    while i < len(data):
        t = data[i][0]
        d = c = 0
        while i < len(data) and data[i][0] == t:
            d += data[i][1]
            c += 1
            i += 1
        if at_risk and d:
            s *= 1 - d / at_risk
            curve.append((t, s))
        at_risk -= c
    for h in horizons:
        val = None
        for t, sv in curve:
            if t <= h:
                val = sv
        res[f"rfs_{h}m"] = val if data and data[-1][0] >= h else None
    res["n"] = len(data)
    return res


# ---------------------------------------------------------------- METABRIC
def _breast_subtype(p: dict) -> str:
    hr = "positivo" in (p.get("re"), p.get("rp"))
    if p.get("her2") == "positivo":
        return "HR+/HER2+" if hr else "HER2+"
    return "HR+/HER2-" if hr else "TNBC"


def _sample_metabric(strata: dict[str, int], seed: int) -> list[dict]:
    cases = [c for c in map(metabric.to_case, metabric.download()) if c]
    by: dict[str, list] = {}
    for c in cases:
        by.setdefault(_breast_subtype(c["payload"]), []).append(c)
    rng = random.Random(seed)
    sample = []
    for sub, n in strata.items():
        pool = by.get(sub, [])
        sample += rng.sample(pool, min(n, len(pool)))
    return sample


def evaluate_metabric(client: JevClient, strata=None, seed: int = 42, workers: int = 8, progress: Progress = None) -> dict:
    strata = strata or DEFAULT_STRATA
    sample = _sample_metabric(strata, seed)

    def one(case: dict) -> dict:
        r = run("mama", case["payload"], client=client)
        rec = r.get("recomendacion_principal") or {}
        rec_id = rec.get("id")
        probs = {}
        for capa in r.get("explicabilidad", []):
            if "mejor_opcion" in capa["respuestas"]:
                probs = capa["respuestas"]["mejor_opcion"].get("probabilidades") or {}
        p_chemo = sum(float(v) for k, v in probs.items() if k in CHEMO_OPTIONS) if probs else (1.0 if rec_id in CHEMO_OPTIONS else 0.0)
        t = case["truth"]
        return {
            "patient_id": t["patient_id"],
            "subtipo": (r.get("derivados") or {}).get("Subtipo molecular"),
            "estadio": case["payload"]["estadio"],
            "edad": case["payload"]["edad"],
            "grado": case["payload"].get("grado_histologico"),
            "tamano_mm": case["payload"].get("tamano_tumor_mm"),
            "ganglios": case["payload"].get("ganglios_positivos"),
            "recomendacion": rec.get("label"),
            "recomendacion_id": rec_id,
            "confianza": r.get("confianza"),
            "revision": r.get("requiere_revision_humana"),
            "pred_quimio": rec_id in CHEMO_OPTIONS,
            "p_quimio": p_chemo,
            "pred_endocrino": _breast_subtype(case["payload"]).startswith("HR+"),
            "real_quimio": t["quimioterapia"],
            "real_endocrino": t["endocrino"],
            "rfs_months": t["rfs_months"],
            "rfs_event": t["rfs_event"],
            "modelo_jev": r.get("modelo_jev"),
        }

    rows = _parallel(one, sample, workers, progress, "METABRIC")

    by_sub: dict[str, Any] = {}
    for sub in strata:
        rs = [x for x in rows if x["subtipo"] == sub]
        by_sub[sub] = {
            "n": len(rs),
            "quimio": _binary([(x["pred_quimio"], x["real_quimio"]) for x in rs]),
            "endocrino": _binary([(x["pred_endocrino"], x["real_endocrino"]) for x in rs]),
            "revision_pct": sum(bool(x["revision"]) for x in rs) / len(rs) if rs else None,
        }

    # Decision real de Jev: quimio si/no en HR+/HER2- precoz.
    lum = [x for x in rows if x["subtipo"] == "HR+/HER2-" and x["estadio"] != "IV"]
    buckets = []
    for lo, hi in ((0.0, 0.6), (0.6, 0.8), (0.8, 0.9), (0.9, 1.01)):
        b = [x for x in lum if x["confianza"] is not None and lo <= x["confianza"] < hi]
        buckets.append({
            "rango": f"{lo:.0%}-{min(hi, 1):.0%}",
            "n": len(b),
            "concordancia": (sum(x["pred_quimio"] == x["real_quimio"] for x in b) / len(b)) if b else None,
        })
    no_chemo = [x for x in lum if not x["real_quimio"]]
    pronostico = {
        "jev_alto_riesgo": _km([x["rfs_months"] for x in no_chemo if x["pred_quimio"]],
                               [x["rfs_event"] for x in no_chemo if x["pred_quimio"]]),
        "jev_bajo_riesgo": _km([x["rfs_months"] for x in no_chemo if not x["pred_quimio"]],
                               [x["rfs_event"] for x in no_chemo if not x["pred_quimio"]]),
    }

    return {
        "n": len(rows),
        "strata": strata,
        "seed": seed,
        "global": {
            "quimio": _binary([(x["pred_quimio"], x["real_quimio"]) for x in rows]),
            "endocrino": _binary([(x["pred_endocrino"], x["real_endocrino"]) for x in rows]),
            "revision_pct": sum(bool(x["revision"]) for x in rows) / len(rows) if rows else None,
            "confianza_media": _mean([x["confianza"] for x in rows]),
        },
        "por_subtipo": by_sub,
        "luminal_precoz": {
            "n": len(lum),
            "quimio": _binary([(x["pred_quimio"], x["real_quimio"]) for x in lum]),
            "auc_p_quimio": _auc([x["p_quimio"] for x in lum], [x["real_quimio"] for x in lum]),
            "calibracion": buckets,
            "pronostico_sin_quimio": pronostico,
        },
        "casos": rows,
    }


def _mean(v: list) -> Optional[float]:
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


# ---------------------------------------------------------------- MSK-CHORD
def _km_os(times: list, events: list) -> dict:
    data = sorted((t, e) for t, e in zip(times, events) if t is not None)
    s, at_risk, i, curve = 1.0, len(data), 0, [(0.0, 1.0)]
    while i < len(data):
        t = data[i][0]
        d = c = 0
        while i < len(data) and data[i][0] == t:
            d += data[i][1]
            c += 1
            i += 1
        if at_risk and d:
            s *= 1 - d / at_risk
            curve.append((t, s))
        at_risk -= c
    def at(h):
        if not data or data[-1][0] < h:
            return None
        return [sv for t, sv in curve if t <= h][-1]
    med = next((t for t, sv in curve if sv <= 0.5), None)
    return {"n": len(data), "os_12m": at(12), "os_24m": at(24), "mediana_meses": med}


def evaluate_msk_chord(client: JevClient, n_per_tumor: int = 60, seed: int = 42, workers: int = 8,
                       progress: Progress = None) -> dict:
    out: dict[str, Any] = {"n_por_tumor": n_per_tumor, "seed": seed, "tumores": {}}
    all_cases: dict[str, list] = {}
    for tumor in msk_chord.CANCER_TYPES:
        cases = msk_chord.build_cases(tumor, n=n_per_tumor, seed=seed, workers=workers)
        cmap = msk_chord.OPTION_CLASS[tumor]
        compat = msk_chord.COMPATIBLE[tumor]

        def one(case: dict, tumor=tumor, cmap=cmap, compat=compat) -> dict:
            try:
                r = run(tumor, case["payload"], client=client)
            except Exception as exc:
                r = {"status": "error", "error": str(exc)}
            rec = (r.get("recomendacion_principal") or {}) if r.get("status") == "ok" else {}
            jc = cmap.get(rec.get("id")) if rec else None
            t = case["truth"]
            return {
                "patient_id": t["patient_id"], "subgrupo": msk_chord.subgroup(tumor, case["payload"]),
                "ecog": case["payload"].get("ecog"), "status": r.get("status"),
                "preguntas": r.get("preguntas", []), "recomendacion_id": rec.get("id"),
                "recomendacion": rec.get("label"), "clase_jev": jc, "clase_recibida": t["clase_recibida"],
                "agentes_1l": t["agentes_1l"], "exacta": jc is not None and jc == t["clase_recibida"],
                "compatible": jc is not None and (jc == t["clase_recibida"] or t["clase_recibida"] in compat.get(jc, set())),
                "confianza": r.get("confianza"), "revision": r.get("requiere_revision_humana"),
                "os_months": t["os_months"], "os_event": t["os_event"], "imputaciones": t["imputaciones"],
                "modelo_jev": r.get("modelo_jev"),
            }

        rows = _parallel(one, cases, workers, progress, f"MSK-CHORD {tumor}")
        all_cases[tumor] = rows
        ev = [x for x in rows if x["clase_jev"]]
        frac = lambda xs, k: (sum(bool(x[k]) for x in xs) / len(xs)) if xs else None  # noqa: E731
        sub: dict[str, Any] = {}
        for g in sorted({x["subgrupo"] for x in rows}):
            xs = [x for x in ev if x["subgrupo"] == g]
            sub[g] = {"n": len([x for x in rows if x["subgrupo"] == g]), "evaluables": len(xs),
                      "exacta": frac(xs, "exacta"), "compatible": frac(xs, "compatible")}
        matriz: dict[str, dict[str, int]] = {}
        for x in ev:
            matriz.setdefault(x["clase_jev"], {}).setdefault(x["clase_recibida"], 0)
            matriz[x["clase_jev"]][x["clase_recibida"]] += 1
        conc = [x for x in ev if x["compatible"]]
        disc = [x for x in ev if not x["compatible"]]
        res = {
            "tumor": tumor, "nombre": load_all()[tumor].nombre, "n": len(rows), "evaluables": len(ev),
            "necesita_datos": sum(x["status"] == "necesita_datos" for x in rows),
            "sin_opcion": sum(x["status"] == "ok" and not x["clase_jev"] for x in rows),
            "exacta": frac(ev, "exacta"), "compatible": frac(ev, "compatible"),
            "cobertura": len(ev) / len(rows) if rows else None,
            "compatible_itt": sum(bool(x["compatible"]) for x in rows) / len(rows) if rows else None,
            "compatible_nota": msk_chord.COMPATIBLE_NOTE[tumor],
            "revision_pct": frac([x for x in rows if x["status"] == "ok"], "revision"),
            "confianza_media": _mean([x["confianza"] for x in ev]),
            "por_subgrupo": sub, "matriz": matriz,
            "os_concordante": _km_os([x["os_months"] for x in conc], [x["os_event"] for x in conc]),
            "os_discordante": _km_os([x["os_months"] for x in disc], [x["os_event"] for x in disc]),
            "preguntas_frecuentes": sorted({q for x in rows for q in x["preguntas"]})[:5],
        }
        if tumor == "cpnm_metastasico":
            drv = [x for x in ev if x["subgrupo"] == "Con driver accionable"]
            got = [x for x in drv if x["clase_recibida"] == "dirigida"]
            nogot = [x for x in drv if x["clase_recibida"] != "dirigida"]
            res["driver_dirigida"] = {
                "jev_recomienda_dirigida": frac([dict(x, _d=x["clase_jev"] == "dirigida") for x in drv], "_d"),
                "os_recibio_dirigida": _km_os([x["os_months"] for x in got], [x["os_event"] for x in got]),
                "os_no_recibio_dirigida": _km_os([x["os_months"] for x in nogot], [x["os_event"] for x in nogot]),
            }
        out["tumores"][tumor] = res
    ev_all = [x for rows in all_cases.values() for x in rows if x["clase_jev"]]
    out["global"] = {
        "n": sum(len(v) for v in all_cases.values()), "evaluables": len(ev_all),
        "exacta": sum(x["exacta"] for x in ev_all) / len(ev_all) if ev_all else None,
        "compatible": sum(x["compatible"] for x in ev_all) / len(ev_all) if ev_all else None,
        "cobertura": len(ev_all) / max(1, sum(len(v) for v in all_cases.values())),
        "compatible_itt": sum(bool(x["compatible"]) for v in all_cases.values() for x in v)
        / max(1, sum(len(v) for v in all_cases.values())),
        "os_concordante": _km_os([x["os_months"] for x in ev_all if x["compatible"]], [x["os_event"] for x in ev_all if x["compatible"]]),
        "os_discordante": _km_os([x["os_months"] for x in ev_all if not x["compatible"]], [x["os_event"] for x in ev_all if not x["compatible"]]),
    }
    out.update(_run_meta(client, [x for v in all_cases.values() for x in v]))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    MSK_RESULTS.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    MSK_CASES.write_text(json.dumps(all_cases, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return out


# ---------------------------------------------------------------- Vinetas ESMO
# Motivos de revision que no demuestran que la logica de seguridad haya funcionado: una viñeta de
# seguridad que solo se escala por ellos "acierta por casualidad".
SOFT_REASONS = {"modo_simulado", "confianza_baja", "opciones_equilibradas"}


def _score_vignette(tumor_id: str, v, client: JevClient) -> dict:
    try:
        r = run(tumor_id, v.payload, client=client)
    except Exception as exc:  # un spec roto no debe tumbar la evaluacion completa
        r = {"status": "error", "error": str(exc)}
    exp = v.esperado
    rec = (r.get("recomendacion_principal") or {}) if r["status"] == "ok" else {}
    motivos = [m["codigo"] for m in r.get("motivos_revision") or []]
    if exp.tipo == "necesita_datos":
        ok = r["status"] == "necesita_datos"
        pref = ok
        obtenido = "necesita_datos" if ok else (rec.get("id") or r["status"])
    elif exp.tipo == "revision_humana":
        ok = r["status"] == "ok" and bool(r.get("requiere_revision_humana"))
        pref = ok and bool(set(motivos) - SOFT_REASONS)
        obtenido = f"revision ({rec.get('id') or 'sin opcion segura'})" if ok else (rec.get("id") or r["status"])
    else:
        obtenido = rec.get("id") if r["status"] == "ok" else r["status"]
        ok = obtenido in exp.aceptables
        pref = obtenido == exp.preferida
    return {
        "id": v.id, "titulo": v.titulo, "fuente": v.fuente,
        "esperado_tipo": exp.tipo,
        "esperado": exp.preferida or exp.tipo,
        "aceptables": exp.aceptables,
        "obtenido": obtenido,
        "obtenido_label": rec.get("label"),
        "confianza": r.get("confianza"),
        "revision": r.get("requiere_revision_humana"),
        "motivos_revision": motivos,
        "acierto": ok,
        "acierto_preferida": pref,
        "preguntas": r.get("preguntas", []),
        "n_candidatos": len(r.get("candidatos") or []),
        "error": r.get("error"),
        "modelo_jev": r.get("modelo_jev"),
    }


def _summary(rows: list[dict]) -> dict:
    tto = [x for x in rows if x["esperado_tipo"] == "recomendacion"]
    seg = [x for x in rows if x["esperado_tipo"] != "recomendacion"]
    frac = lambda xs, k="acierto": (sum(bool(x[k]) for x in xs) / len(xs)) if xs else None  # noqa: E731
    return {
        "n": len(rows),
        "aciertos": sum(bool(x["acierto"]) for x in rows),
        "acierto_global": frac(rows),
        "acierto_tratamiento": frac(tto),
        "acierto_preferida": frac(tto, "acierto_preferida"),
        "acierto_seguridad": frac(seg),
        # Seguridad robusta: casos de revision escalados por un motivo determinista/de seguridad,
        # no solo por baja confianza del modelo.
        "acierto_seguridad_robusta": frac(seg, "acierto_preferida"),
        "tratamiento_sin_revision": (sum(bool(x["acierto"]) and not x["revision"] for x in tto) / len(tto)) if tto else None,
        "pct_tratamiento_con_revision": frac(tto, "revision"),
        "confianza_aciertos": _mean([x["confianza"] for x in tto if x["acierto"]]),
        "confianza_fallos": _mean([x["confianza"] for x in tto if not x["acierto"]]),
        # Dificultad: casos de tratamiento en los que Jev tuvo que elegir entre >=2 opciones ESMO.
        "n_multiopcion": len(multi := [x for x in tto if (x.get("n_candidatos") or 0) >= 2]),
        "acierto_multiopcion": frac(multi),
        "candidatos_medios": _mean([x.get("n_candidatos") for x in tto]),
    }


def evaluate_tumor(tumor_id: str, client: Optional[JevClient] = None, workers: int = 8,
                   progress: Progress = None, save: bool = True) -> dict:
    client = client or JevClient()
    spec = get_spec(tumor_id)
    rows = _parallel(lambda v: _score_vignette(tumor_id, v, client), spec.vinetas, workers, progress, spec.nombre)
    rows.sort(key=lambda x: x["id"])
    res = {
        "tumor": spec.id, "nombre": spec.nombre, "grupo": spec.grupo, "version": spec.version,
        **_run_meta(client, rows), "umbral_confianza": CONFIDENCE_THRESHOLD,
        **_summary(rows), "casos": rows,
    }
    if save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / f"{tumor_id}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return res


def run_all(client: Optional[JevClient] = None, tumors: Optional[list[str]] = None, metabric_too: bool = True,
            strata=None, seed: int = 42, progress: Progress = None, msk_too: bool = False, msk_n: int = 60) -> dict:
    client = client or JevClient()
    tumors = tumors or list(load_all())
    out = {t: evaluate_tumor(t, client, progress=progress) for t in tumors}
    if metabric_too:
        m = evaluate_metabric(client, strata=strata, seed=seed, progress=progress)
        m.update(_run_meta(client, m.get("casos") or []))
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        METABRIC_RESULTS.write_text(json.dumps(m, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if msk_too:
        evaluate_msk_chord(client, n_per_tumor=msk_n, seed=seed, progress=progress)
    return load_results()


def load_results() -> dict:
    """{"tumores": {id: resultado}, "metabric": resultado|None, "global": resumen}"""
    tum = {}
    if RESULTS_DIR.exists():
        for f in sorted(RESULTS_DIR.glob("*.json")):
            if not f.name.startswith("_"):
                tum[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    met = json.loads(METABRIC_RESULTS.read_text(encoding="utf-8")) if METABRIC_RESULTS.exists() else None
    rows = [c for r in tum.values() for c in r["casos"]]
    msk = json.loads(MSK_RESULTS.read_text(encoding="utf-8")) if MSK_RESULTS.exists() else None
    if msk and MSK_CASES.exists():
        msk["casos"] = json.loads(MSK_CASES.read_text(encoding="utf-8"))
    return {"tumores": tum, "metabric": met, "msk_chord": msk, "global": _summary(rows) if rows else None}

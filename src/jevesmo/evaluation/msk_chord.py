"""Cohorte real MSK-CHORD (Jee et al., Nature 2024; cBioPortal `msk_chord_2024`).

~25.000 pacientes de Memorial Sloan Kettering (practica ~2014-2022) con
secuenciacion MSK-IMPACT, estadio, ECOG, lineas de tratamiento con farmacos y
fechas relativas, y supervivencia global. Licencia CC BY-NC-ND 4.0: los datos
se descargan de cBioPortal a una cache local (data/msk_chord/, no versionada);
solo se publican metricas agregadas.

Aqui se reconstruye, para pacientes con enfermedad **metastasica de novo**
(diagnostico primario AJCC IV), la ficha que veria el oncologo al decidir la
**primera linea** y el tratamiento que realmente recibieron, para 4 tumores:
CPNM metastasico, cancer colorrectal metastasico, pancreas metastasico y mama
metastasica.
"""

from __future__ import annotations

import json
import random
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from .metabric import DATA_DIR

API = "https://www.cbioportal.org/api"
STUDY = "msk_chord_2024"
CACHE_DIR = DATA_DIR / "msk_chord"

CANCER_TYPES = {
    "cpnm_metastasico": "Non-Small Cell Lung Cancer",
    "ccr_metastasico": "Colorectal Cancer",
    "pancreas": "Pancreatic Cancer",
    "mama": "Breast Cancer",
}

GENES = {  # entrez ids
    "EGFR": 1956, "KRAS": 3845, "NRAS": 4893, "BRAF": 673, "MET": 4233, "ERBB2": 2064,
    "PIK3CA": 5290, "ESR1": 2099, "BRCA1": 672, "BRCA2": 675, "AKT1": 207, "PTEN": 5728,
}
FUSION_GENES = {"ALK": 238, "ROS1": 6098, "RET": 5979, "NTRK1": 4914, "NTRK2": 4915, "NTRK3": 4916}

SYSTEMIC = {"Chemo", "Immuno", "Targeted", "Biologic", "Hormone", "Investigational"}


# ------------------------------------------------------------------ HTTP
def _get(path: str) -> Any:
    req = urllib.request.Request(API + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(path: str, body: Any) -> Any:
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(),
                                 headers={"Accept": "application/json", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode("utf-8"))


def _cached(name: str, fn, force: bool = False) -> Any:
    f = CACHE_DIR / name
    if f.exists() and not force:
        return json.loads(f.read_text(encoding="utf-8"))
    data = fn()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


# ------------------------------------------------------------------ descarga
def _clinical(kind: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    key = "patientId" if kind == "PATIENT" else "sampleId"
    for it in _get(f"/studies/{STUDY}/clinical-data?clinicalDataType={kind}&projection=SUMMARY&pageSize=10000000"):
        rows.setdefault(it[key], {"patientId": it["patientId"]})[it["clinicalAttributeId"]] = it["value"]
    return rows


def _mutations() -> list[dict]:
    m = _post(f"/molecular-profiles/{STUDY}_mutations/mutations/fetch?projection=SUMMARY",
              {"sampleListId": f"{STUDY}_all", "entrezGeneIds": list(GENES.values())})
    inv = {v: k for k, v in GENES.items()}
    return [{"s": x["sampleId"], "g": inv.get(x["entrezGeneId"]), "p": x.get("proteinChange") or "",
             "t": x.get("mutationType") or ""} for x in m]


def _fusions() -> list[dict]:
    sv = _post("/structural-variant/fetch", {"molecularProfileIds": [f"{STUDY}_structural_variants"],
                                             "entrezGeneIds": list(FUSION_GENES.values())})
    out = []
    for x in sv:
        genes = {x.get("site1HugoSymbol"), x.get("site2HugoSymbol")} & set(FUSION_GENES)
        info = f"{x.get('eventInfo') or ''} {x.get('annotation') or ''}".lower()
        if genes and ("fusion" in info or "rearrangement" in info):
            out += [{"s": x["sampleId"], "g": g} for g in genes]
    return out


def _timeline(pid: str) -> dict:
    ev = _get(f"/studies/{STUDY}/patients/{pid}/clinical-events?pageSize=100000")
    keep = []
    for x in ev:
        a = {k["key"]: k["value"] for k in x["attributes"]}
        sub = a.get("SUBTYPE")
        if (x["eventType"] == "Treatment" and sub in SYSTEMIC) or sub in ("Primary", "Performance Status"):
            keep.append({"e": x["eventType"], "st": sub, "d0": x.get("startNumberOfDaysSinceDiagnosis"),
                         "d1": x.get("endNumberOfDaysSinceDiagnosis"),
                         "a": {k: v for k, v in a.items() if k in ("AGENT", "AJCC", "STAGE_CDM_DERIVED", "DX_DESCRIPTION", "ECOG")}})
    return {"pid": pid, "ev": keep}


def download(force: bool = False) -> dict[str, Any]:
    return {
        "patients": _cached("patients.json", lambda: _clinical("PATIENT"), force),
        "samples": _cached("samples.json", lambda: _clinical("SAMPLE"), force),
        "mutations": _cached("mutations.json", _mutations, force),
        "fusions": _cached("fusions.json", _fusions, force),
    }


def timelines(pids: list[str], workers: int = 8) -> dict[str, dict]:
    f = CACHE_DIR / "timelines.json"
    cache: dict[str, dict] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    todo = [p for p in pids if p not in cache]
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for t in ex.map(_safe_timeline, todo):
                if t:
                    cache[t["pid"]] = t
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return {p: cache[p] for p in pids if p in cache}


def _safe_timeline(pid: str) -> Optional[dict]:
    try:
        return _timeline(pid)
    except Exception:
        return None


# ------------------------------------------------------------------ biomarcadores
EGFR_EX19 = re.compile(r"^[ELTKSAP]7(4[5-9]|5\d)_")


def _egfr(p: str) -> Optional[str]:
    if p == "L858R" or EGFR_EX19.match(p) and ("del" in p):
        return "egfr_comun"
    if "ins" in p or "dup" in p:
        m = re.match(r"^[A-Z](\d+)", p)
        if m and 762 <= int(m.group(1)) <= 775:
            return "egfr_exon20"
    if re.match(r"^(G719|L861Q|S768I)", p):
        return "egfr_comun"  # mutaciones poco comunes sensibles a TKI (afatinib/osimertinib)
    return None


def _molecular(mut: list[dict], fus: list[dict]) -> dict[str, dict]:
    by: dict[str, dict] = {}
    for x in mut:
        d = by.setdefault(x["s"], {"mut": [], "fus": set()})
        d["mut"].append((x["g"], x["p"], x["t"]))
    for x in fus:
        by.setdefault(x["s"], {"mut": [], "fus": set()})["fus"].add(x["g"])
    return by


def _has(mol: dict, gene: str, pred=lambda p, t: True) -> bool:
    return any(g == gene and pred(p, t) for g, p, t in mol.get("mut", []))


RAS_HOT = re.compile(r"^[A-Z](12|13|59|61|117|146)[A-Z*]")


def _nsclc_driver(mol: dict) -> str:
    for g, p, _ in mol.get("mut", []):
        if g == "EGFR" and _egfr(p):
            return _egfr(p)
    fus = mol.get("fus", set())
    if "ALK" in fus:
        return "alk"
    if "ROS1" in fus:
        return "ros1"
    if "RET" in fus:
        return "ret"
    if fus & {"NTRK1", "NTRK2", "NTRK3"}:
        return "ntrk"
    if _has(mol, "BRAF", lambda p, t: p == "V600E"):
        return "braf_v600e"
    if _has(mol, "MET", lambda p, t: "splice" in t.lower() or "splice" in p.lower() or "X1010" in p or p.startswith("D1010") or "963_" in p or "exon14" in p.lower()):
        return "met_ex14"
    if _has(mol, "ERBB2", lambda p, t: ("ins" in p or "dup" in p) and re.match(r"^[A-Z]7[67]\d", p)) or _has(mol, "ERBB2", lambda p, t: p in ("S310F", "L755S", "V777L")):
        return "her2_mutado"
    if _has(mol, "KRAS", lambda p, t: p == "G12C"):
        return "kras_g12c"
    return "ninguno"


# ------------------------------------------------------------------ tratamiento recibido
def _first_line(tl: dict) -> Optional[dict]:
    ev = tl["ev"]
    prim = [x for x in ev if x["st"] == "Primary" and ("IV" in (x["a"].get("AJCC") or "") or x["a"].get("STAGE_CDM_DERIVED") == "Stage 4")]
    if not prim:
        return None
    dx = min(x["d0"] for x in prim if x["d0"] is not None)
    tx = sorted((x for x in ev if x["e"] == "Treatment" and x["d0"] is not None and x["d0"] >= dx - 30),
                key=lambda x: x["d0"])
    if not tx or tx[0]["d0"] > dx + 180:
        return None
    t0 = tx[0]["d0"]
    reg = sorted({(x["a"].get("AGENT") or "").upper() for x in tx
                  if x["d0"] <= t0 + 42 or (x["d0"] <= t0 + 90 and (x["a"].get("AGENT") or "").upper() in ADD_ON)} - {""})
    subtypes = sorted({x["st"] for x in tx if x["d0"] <= t0 + 42})
    ps = [x for x in ev if x["st"] == "Performance Status" and x["d0"] is not None and abs(x["d0"] - t0) <= 60]
    ecog = min(ps, key=lambda x: abs(x["d0"] - t0))["a"].get("ECOG") if ps else None
    later = sorted({(x["a"].get("AGENT") or "").upper() for x in tx if x["d0"] > t0 + 42} - set(reg) - {""})
    return {"dx_day": dx, "t0": t0, "agentes": reg, "subtipos": subtypes, "ecog": ecog,
            "dx_desc": prim[0]["a"].get("DX_DESCRIPTION") or "", "posteriores": later[:12]}


# Biologicos que en la practica se anaden a la quimio en los primeros ciclos.
ADD_ON = {"BEVACIZUMAB", "CETUXIMAB", "PANITUMUMAB", "TRASTUZUMAB", "PERTUZUMAB", "PEMBROLIZUMAB", "ATEZOLIZUMAB",
          "NIVOLUMAB", "DURVALUMAB"}

EGFR_TKI = {"OSIMERTINIB", "ERLOTINIB", "GEFITINIB", "AFATINIB", "DACOMITINIB", "AMIVANTAMAB", "LAZERTINIB", "MOBOCERTINIB"}
ALK_ROS_TKI = {"CRIZOTINIB", "ALECTINIB", "BRIGATINIB", "LORLATINIB", "CERITINIB", "ENTRECTINIB", "REPOTRECTINIB",
               "LAROTRECTINIB", "SELPERCATINIB", "PRALSETINIB", "CABOZANTINIB", "CAPMATINIB", "TEPOTINIB",
               "DABRAFENIB", "TRAMETINIB", "SOTORASIB", "ADAGRASIB", "TRASTUZUMAB DERUXTECAN", "VEMURAFENIB"}
ICI = {"PEMBROLIZUMAB", "NIVOLUMAB", "ATEZOLIZUMAB", "DURVALUMAB", "IPILIMUMAB", "CEMIPLIMAB", "TREMELIMUMAB", "DOSTARLIMAB"}
ANTI_EGFR = {"CETUXIMAB", "PANITUMUMAB"}
CDK46 = {"PALBOCICLIB", "RIBOCICLIB", "ABEMACICLIB"}
ANTI_HER2 = {"TRASTUZUMAB", "PERTUZUMAB", "ADO-TRASTUZUMAB EMTANSINE", "TRASTUZUMAB EMTANSINE", "TRASTUZUMAB DERUXTECAN",
             "LAPATINIB", "NERATINIB", "TUCATINIB", "MARGETUXIMAB"}
PARP = {"OLAPARIB", "TALAZOPARIB", "NIRAPARIB", "RUCAPARIB"}
BREAST_ENDO = {"LETROZOLE", "ANASTROZOLE", "EXEMESTANE", "FULVESTRANT", "TAMOXIFEN", "GOSERELIN", "LEUPROLIDE", "ELACESTRANT"}


def received_class(tumor: str, agentes: list[str]) -> str:
    a = set(agentes) - {"INVESTIGATIONAL"}
    if not a:
        return "otro"  # solo ensayo clinico: no comparable
    if tumor == "cpnm_metastasico":
        if a & (EGFR_TKI | ALK_ROS_TKI):
            return "dirigida"
        if a & ICI:
            return "inmunoterapia"
        return "quimio" if a else "otro"
    if tumor == "ccr_metastasico":
        if a & ICI:
            return "inmunoterapia"
        if a & ANTI_EGFR:
            return "quimio_anti_egfr"
        if "BEVACIZUMAB" in a:
            return "quimio_bev"
        return "quimio_sola" if a else "otro"
    if tumor == "pancreas":
        if a & ICI:
            return "inmunoterapia"
        if {"OXALIPLATIN", "IRINOTECAN"} <= a or "IRINOTECAN LIPOSOME" in a:
            return "folfirinox"
        if "GEMCITABINE" in a and ("PACLITAXEL PROTEIN-BOUND" in a or "NAB-PACLITAXEL" in a or "PACLITAXEL" in a):
            return "gem_nab"
        if "GEMCITABINE" in a:
            return "gemcitabina_sola"
        return "otra_quimio" if a else "otro"
    if tumor == "mama":
        if a & ANTI_HER2:
            return "anti_her2"
        if a & CDK46:
            return "endocrino_cdk46"
        if a & PARP:
            return "parp"
        if a & ICI:
            return "quimio_ici"
        if a & BREAST_ENDO and not (a - BREAST_ENDO - {"DENOSUMAB", "ZOLEDRONIC ACID"}):
            return "endocrino_solo"
        return "quimio" if a else "otro"
    return "otro"


# Clase terapeutica de cada opcion del arbol ESMO (para comparar con lo recibido).
OPTION_CLASS = {
    "cpnm_metastasico": {
        "osimertinib_1l": "dirigida", "amivantamab_lazertinib_1l": "dirigida", "amivantamab_exon20": "dirigida",
        "alectinib_alk": "dirigida", "entrectinib_ros1_ntrk": "dirigida", "dabrafenib_trametinib": "dirigida",
        "selpercatinib_ret": "dirigida", "capmatinib_tepotinib_met": "dirigida", "kras_g12c_2l": "dirigida",
        "tdxd_her2_2l": "dirigida", "pembro_monoterapia": "inmunoterapia", "quimio_ici_noescamoso": "inmunoterapia",
        "quimio_ici_escamoso": "inmunoterapia", "docetaxel_nintedanib": "quimio",
    },
    "ccr_metastasico": {
        "doublet_egfr_izq_1l": "quimio_anti_egfr", "doublet_bev_1l": "quimio_bev", "folfoxiri_bev_conversion": "quimio_bev",
        "pembro_msi_1l": "inmunoterapia", "nivolumab_ipilimumab_msi": "inmunoterapia", "encorafenib_cetuximab": "dirigida",
        "her2_tucatinib_trastuzumab": "dirigida", "g12c_egfr": "dirigida", "tas102_bev": "quimio_bev",
        "fruquintinib": "dirigida", "cirugia_metastasectomia": "cirugia", "soporte_mcrc": "soporte",
    },
    "pancreas": {
        "mfolfirinox_1l": "folfirinox", "nalirifox_1l": "folfirinox", "gemnab_1l": "gem_nab",
        "olaparib_mantenimiento": "parp", "pembro_msi_h": "inmunoterapia", "naliri_5fu_2l": "otra_quimio",
        "folfox_2l": "otra_quimio",
    },
    "mama": {
        "endocrino_cdk46_1L": "endocrino_cdk46", "fulvestrant_2L": "endocrino_solo", "pi3k_inhibidor_2L": "endocrino_cdk46",
        "quimio_metastasico": "quimio", "th_pertuzumab_1L": "anti_her2", "tdxd_2L": "anti_her2", "tucatinib_combo": "anti_her2",
        "endocrino_add_on": "anti_her2", "quimio_ici_1L": "quimio_ici", "parp_metastasico": "parp",
        "sacituzumab_govitecan": "quimio", "quimio_metastasico_tnbc": "quimio",
    },
}


# Clases recibidas que se consideran compatibles (no identicas) con la recomendacion de Jev.
COMPATIBLE = {
    "ccr_metastasico": {"quimio_bev": {"quimio_sola"}, "quimio_anti_egfr": {"quimio_sola"}},
    "pancreas": {"folfirinox": {"gem_nab"}, "gem_nab": {"folfirinox", "gemcitabina_sola"}},
    "mama": {"endocrino_cdk46": {"endocrino_solo"}},
    "cpnm_metastasico": {},
}
COMPATIBLE_NOTE = {
    "ccr_metastasico": "misma quimio doblete sin (o con retraso >90 d del) biologico",
    "pancreas": "FOLFIRINOX y gemcitabina-nab-paclitaxel son ambas opciones ESMO en ECOG 0-1",
    "mama": "endocrino sin iCDK4/6 (mismo eje terapeutico)",
    "cpnm_metastasico": "sin compatibilidades parciales",
}


def subgroup(tumor: str, p: dict) -> str:
    if tumor == "cpnm_metastasico":
        d = p.get("driver")
        if d in (None, "ninguno"):
            return "Sin driver"
        return "KRAS G12C / HER2 mut (dirigida en 2L)" if d in ("kras_g12c", "her2_mutado") else "Con driver accionable"
    if tumor == "ccr_metastasico":
        if p.get("msi") == "si":
            return "MSI-H"
        return f"RAS {p.get('ras')} · {p.get('lateralidad')}"
    if tumor == "pancreas":
        return f"ECOG {p.get('ecog')}"
    if tumor == "mama":
        hr = p.get("re") == "positivo"
        her2 = p.get("her2") == "positivo"
        return "HR+/HER2+" if hr and her2 else "HER2+" if her2 else "HR+/HER2-" if hr else "TNBC"
    return "-"


# ------------------------------------------------------------------ ficha clinica
def _yesno(v: Any) -> Optional[bool]:
    s = str(v or "").strip().lower()
    return True if s in ("yes", "positive", "y") else False if s in ("no", "negative", "n") else None


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


RIGHT = ("CECUM", "ASCENDING", "HEPATIC FLEXURE", "TRANSVERSE", "APPENDIX")
LEFT = ("SPLENIC FLEXURE", "DESCENDING", "SIGMOID", "RECTOSIGMOID", "RECTUM", "RECTAL")


def build_payload(tumor: str, pat: dict, samp: dict, mol: dict, fl: dict) -> tuple[dict, list[str]]:
    imput: list[str] = []
    age_now, os_m = _num(pat.get("CURRENT_AGE_DEID")), _num(pat.get("OS_MONTHS")) or 0
    edad = int(round(age_now - os_m / 12)) if age_now else None
    p: dict[str, Any] = {"edad": edad, "sexo": "mujer" if (pat.get("GENDER") or "").lower() == "female" else "hombre",
                         "ecog": fl["ecog"], "lineas_previas": 0}
    imput.append("edad aproximada = edad actual - seguimiento")
    detail = (samp.get("CANCER_TYPE_DETAILED") or "")
    desc = fl["dx_desc"].upper()
    notas = [f"Diagnostico: {detail}. {fl['dx_desc']}."]

    if tumor == "cpnm_metastasico":
        p["histologia"] = "escamoso" if "squamous" in detail.lower() else "no_escamoso"
        p["driver"] = _nsclc_driver(mol)
        pd = _yesno(samp.get("PDL1_POSITIVE")) if samp.get("PDL1_POSITIVE") else _yesno(pat.get("HISTORY_OF_PDL1"))
        if p["driver"] in ("ninguno", "kras_g12c", "her2_mutado"):
            p["pdl1_tps"] = 1 if pd else 0
            imput.append("PD-L1 TPS no disponible (solo positivo/negativo por NLP): se imputa 1% si positivo, 0% si negativo")
            notas.append(f"PD-L1: {'positivo' if pd else 'negativo/no consta'} (sin TPS cuantificado).")
    elif tumor == "ccr_metastasico":
        ras = _has(mol, "KRAS", lambda q, t: bool(RAS_HOT.match(q))) or _has(mol, "NRAS", lambda q, t: bool(RAS_HOT.match(q)))
        p["ras"] = "mutado" if ras else "wt"
        p["braf_v600e"] = "si" if _has(mol, "BRAF", lambda q, t: q == "V600E") else "no"
        msi = (samp.get("MSI_TYPE") or "").lower()
        p["msi"] = "si" if "instable" in msi or "unstable" in msi else "no" if "stable" in msi else "desconocido"
        p["kras_g12c"] = "si" if _has(mol, "KRAS", lambda q, t: q == "G12C") else "no"
        side = "izquierdo" if any(k in desc for k in LEFT) or "rect" in detail.lower() else "derecho" if any(k in desc for k in RIGHT) else "desconocido"
        p["lateralidad"] = side
        p["resecabilidad"] = "irresecable"
        p["candidato_intensivo"] = fl["ecog"] in ("0", "1")
        imput += ["resecabilidad = irresecable (no consta; metastasico de novo)", "candidato_intensivo = ECOG 0-1"]
    elif tumor == "pancreas":
        p["situacion"] = "metastasico"
        p["localizacion"] = "cuerpo_cola" if ("BODY" in desc or "TAIL" in desc) else "cabeza" if "HEAD" in desc else None
        if p["localizacion"] is None:
            p["localizacion"] = "cabeza"
            imput.append("localizacion = cabeza (no consta; localizacion mas frecuente, sin impacto en la eleccion de 1L metastasica)")
        if _has(mol, "BRCA1") or _has(mol, "BRCA2"):
            p["brca_germinal"] = True
            imput.append("BRCA1/2 alterado en tumor (MSK-IMPACT) tratado como posible germinal")
        msi = (samp.get("MSI_TYPE") or "").lower()
        p["msi"] = "msi_h" if "instable" in msi else "pmmr" if "stable" in msi else "desconocido"
    elif tumor == "mama":
        p["estadio"] = "IV"
        d = detail.lower()
        p["tipo_histologico"] = "lobulillar_invasivo" if "lobular" in d else "ductal_invasivo" if "ductal" in d else "otro"
        hr, her2 = _yesno(pat.get("HR")), _yesno(pat.get("HER2"))
        p["re"] = p["rp"] = None if hr is None else ("positivo" if hr else "negativo")
        p["her2"] = None if her2 is None else ("positivo" if her2 else "negativo")
        p["premenopausica"] = edad is not None and edad < 50
        imput += ["RE/RP = estado HR global", "premenopausica = edad < 50"]
        p["pik3ca_mutado"] = _has(mol, "PIK3CA") or _has(mol, "AKT1", lambda q, t: q == "E17K") or None
        p["esr1_mutado"] = _has(mol, "ESR1") or None
        p["brca_mutado"] = (_has(mol, "BRCA1") or _has(mol, "BRCA2")) or None
    p["descripcion_libre"] = " ".join(notas)
    return p, imput


def build_cases(tumor: str, n: int = 60, seed: int = 42, workers: int = 8) -> list[dict]:
    """Casos evaluables (metastasico de novo con 1a linea sistemica conocida y ECOG)."""
    d = download()
    pats, samps = d["patients"], d["samples"]
    mol = _molecular(d["mutations"], d["fusions"])
    ctype = CANCER_TYPES[tumor]
    by_pat: dict[str, tuple[str, dict]] = {}
    for sid, s in samps.items():
        if s.get("CANCER_TYPE") == ctype and s.get("SAMPLE_TYPE", "Primary") and s["patientId"] not in by_pat:
            by_pat[s["patientId"]] = (sid, s)
    pool = [pid for pid in by_pat if (pats.get(pid, {}).get("STAGE_HIGHEST_RECORDED") == "Stage 4")]
    rng = random.Random(seed)

    # Enriquecer CPNM con drivers para evaluar tambien la rama de terapia dirigida.
    if tumor == "cpnm_metastasico":
        strata: dict[str, list[str]] = {}
        for pid in pool:
            dr = _nsclc_driver(mol.get(by_pat[pid][0], {}))
            strata.setdefault("driver" if dr != "ninguno" else "ninguno", []).append(pid)
        order = []
        for k in ("driver", "ninguno"):
            rng.shuffle(strata.get(k, []))
        dq, nq = strata.get("driver", []), strata.get("ninguno", [])
        while dq or nq:
            if dq:
                order.append(dq.pop())
            if nq:
                order.append(nq.pop())
    else:
        order = pool[:]
        rng.shuffle(order)

    cases: list[dict] = []
    batch = max(n * 3, 60)
    i = 0
    while len(cases) < n and i < len(order):
        chunk = order[i:i + batch]
        i += batch
        tls = timelines(chunk, workers=workers)
        for pid in chunk:
            tl = tls.get(pid)
            fl = _first_line(tl) if tl else None
            if not fl or fl["ecog"] is None:
                continue
            sid, s = by_pat[pid]
            payload, imput = build_payload(tumor, pats[pid], s, mol.get(sid, {}), fl)
            recv = received_class(tumor, fl["agentes"])
            if recv == "otro":
                continue
            os_status = str(pats[pid].get("OS_STATUS") or "")
            cases.append({
                "payload": payload,
                "truth": {"patient_id": pid, "agentes_1l": fl["agentes"], "clase_recibida": recv,
                          "os_months": _num(pats[pid].get("OS_MONTHS")), "os_event": os_status.startswith("1"),
                          "imputaciones": imput},
            })
            if len(cases) >= n:
                break
    return cases
